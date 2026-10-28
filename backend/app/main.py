from fastapi import FastAPI, APIRouter, HTTPException, BackgroundTasks, UploadFile, File, Form, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
import os
import shutil
import tempfile
import logging
from typing import Optional, List, Dict, Any
import re
from git import Repo
from .workspace import WorkspaceManager, get_benchmark_fixtures_dir, resolve_benchmark_fixture_name
from .patch_engine import PatchEngine
from .nebius_client import NebiusClient, NebiusInferenceError
from .github_service import GitHubService, REPO_NAME_REGEX, sanitize_branch_name
from .intent_classifier import classify_intent, RequestIntent
from .repo_inspector import RepoInspector, IGNORE_DIRS, IGNORE_EXTS
from .auth import AuthUser, get_optional_user, get_current_user, supabase_manager
from .crypto import token_encryptor, TokenEncryptionError
from .reporting import compute_finding_fingerprint, format_commit_title

logger = logging.getLogger(__name__)

app = FastAPI(title="Patchworks API", version="0.1.0")

# Configure CORS for multi-service or cross-origin setups
cors_origins_env = os.getenv("CORS_ORIGINS", "*")
cors_origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins if cors_origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

workspace_manager = WorkspaceManager()
nebius_client = NebiusClient()
github_service = GitHubService()

def resolve_github_token(user: Optional[AuthUser] = None, explicit_token: Optional[str] = None) -> Optional[str]:
    """Resolve GitHub token with precedence: explicit request token > authenticated user's encrypted token > guest fallback."""
    if explicit_token and explicit_token.strip():
        return explicit_token.strip()

    if user:
        if supabase_manager.is_configured:
            conn = supabase_manager.get_github_connection(user.id)
            if conn and conn.get("encrypted_access_token"):
                try:
                    decrypted = token_encryptor.decrypt(conn["encrypted_access_token"])
                    return decrypted.strip()
                except TokenEncryptionError as e:
                    logger.error(f"Failed to decrypt stored token for user {user.id}: {e}")
                    return None
        # Authenticated users MUST NOT inherit another user's in-memory session token
        return None

    # Anonymous guest mode fallback
    return github_service.get_token()

def verify_workspace_access(workspace_id: str, user: Optional[AuthUser] = None):
    """Enforce workspace ownership to prevent cross-user workspace tampering."""
    meta = workspace_manager.get_workspace_metadata(workspace_id)
    owner_id = meta.get("user_id") if meta else None
    if owner_id:
        if not user or user.id != owner_id:
            raise HTTPException(
                status_code=403,
                detail="Access denied: workspace belongs to another user"
            )

class BenchmarkWorkspaceRequest(BaseModel):
    fixture: str

class DiagnosisRequest(BaseModel):
    repo_url: Optional[str] = None
    workspace_id: Optional[str] = None
    benchmark: Optional[str] = None
    issue_description: str
    test_command: Optional[str] = None
    mode: Optional[str] = None # 'auto', 'targeted', 'bug_discovery', 'improvement'

class RepairRequest(BaseModel):
    repo_url: Optional[str] = None
    workspace_id: Optional[str] = None
    benchmark: Optional[str] = None
    issue_description: str
    diagnosis_context: Optional[dict] = None
    selected_finding: Optional[dict] = None
    test_command: Optional[str] = None

class BatchRepairRequest(BaseModel):
    workspace_id: str
    finding_ids: List[str]
    test_command: Optional[str] = None

class InspectRequest(BaseModel):
    workspace_id: Optional[str] = None
    benchmark: Optional[str] = None
    repo_url: Optional[str] = None
    test_command: Optional[str] = None

class RollbackRequest(BaseModel):
    workspace_id: str

class GitHubConnectRequest(BaseModel):
    token: str

class GitHubWorkspaceRequest(BaseModel):
    owner: str
    repo: str
    branch: str
    token: Optional[str] = None

class GitHubPublishRequest(BaseModel):
    workspace_id: str
    title: Optional[str] = None
    custom_notes: Optional[str] = None
    token: Optional[str] = None

def redact_secrets(text: str) -> str:
    # Basic secret redaction
    text = re.sub(r'(api_key|API_KEY|secret|SECRET|password|PASSWORD)\s*=\s*["\'][^"\']+["\']', r'\1 = "***REDACTED***"', text)
    text = re.sub(r'(Bearer\s+)[A-Za-z0-9\-\._~]+', r'\1***REDACTED***', text)
    text = re.sub(r'-----BEGIN[A-Z\s]+PRIVATE KEY-----.*?-----END[A-Z\s]+PRIVATE KEY-----', '***REDACTED_PRIVATE_KEY***', text, flags=re.DOTALL)
    return text

def build_context(
    ws_path: str,
    focus_files: Optional[List[str]] = None,
    evidence: Optional[str] = None,
    line_numbers: Optional[List[int]] = None
) -> str:
    code_context = ""
    # If focus files provided, prioritize them
    if focus_files:
        for f in focus_files:
            target = os.path.join(ws_path, f)
            if os.path.isfile(target):
                try:
                    with open(target, 'r', errors='ignore') as fh:
                        raw_content = fh.read()

                    # Smart context slicing for large files
                    if len(raw_content) > 8000:
                        lines = raw_content.splitlines()
                        target_line = None

                        if line_numbers and len(line_numbers) > 0 and line_numbers[0] is not None:
                            target_line = line_numbers[0]

                        if target_line is None and evidence and evidence.strip():
                            ev_clean = evidence.strip().splitlines()[0].strip()
                            if len(ev_clean) >= 6:
                                for l_idx, l_val in enumerate(lines):
                                    if ev_clean in l_val:
                                        target_line = l_idx + 1
                                        break

                        if target_line is not None and 1 <= target_line <= len(lines):
                            start_l = max(0, target_line - 55)
                            end_l = min(len(lines), target_line + 65)
                            sliced_content = "\n".join(lines[start_l:end_l])
                            content = (
                                f"... [lines 1-{start_l} omitted for scope] ...\n"
                                f"{sliced_content}\n"
                                f"... [lines {end_l+1}-{len(lines)} omitted for scope] ..."
                            )
                        else:
                            content = raw_content[:10000] + "\n... [truncated]"
                    else:
                        content = raw_content

                    code_context += f"--- {f} ---\n<untrusted_source_code>\n{redact_secrets(content)}\n</untrusted_source_code>\n\n"
                except Exception:
                    pass
        if len(code_context) > 100:
            return code_context

    for root, dirs, files in os.walk(ws_path):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith('.')]
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext in IGNORE_EXTS or file.endswith("-lock.json"):
                continue

            # Keep common source files
            if file.endswith(('.py', '.js', '.ts', '.tsx', '.jsx', '.json', '.md', '.txt', '.esy', '.toml', '.yaml')):
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, ws_path)
                try:
                    # Skip files larger than 100KB to prevent memory issues
                    if os.path.getsize(file_path) > 100 * 1024:
                        code_context += f"--- {rel_path} ---\n[File truncated: Too large]\n\n"
                        continue

                    with open(file_path, 'r', errors='ignore') as f:
                        content = f.read()

                        # Truncate large files
                        if len(content) > 6000:
                            content = content[:6000] + "\n\n... [File truncated: Exceeds 6,000 characters]"

                        code_context += f"--- {rel_path} ---\n<untrusted_source_code>\n{redact_secrets(content)}\n</untrusted_source_code>\n\n"
                except Exception as e:
                    code_context += f"--- {rel_path} ---\n[Error reading file: {str(e)}]\n\n"

        if len(code_context) > 35000:
            break

    # Cap total context size
    if len(code_context) > 35000:
        code_context = code_context[:35000] + "\n\n... [Context truncated: Exceeds total size limit]"

    return code_context

@app.get("/api/health")
async def health_check():
    return {
        "status": "ok", 
        "message": "Patchworks Backend is running",
        "nebius_configured": not nebius_client.mock_mode,
        "supabase_configured": supabase_manager.is_configured,
        "model": nebius_client.model_name
    }

class SetModelRequest(BaseModel):
    model: str

ALLOWED_NEMOTRON_MODELS = [
    {
        "id": "nvidia/nemotron-3-super-120b-a12b",
        "name": "Nemotron 3 Super (120B MoE)",
        "description": "Specialized for multi-step code synthesis, planning, and agentic workflows.",
        "badge": "Recommended for Code"
    },
    {
        "id": "nvidia/Nemotron-3-Ultra-550b-a55b",
        "name": "Nemotron 3 Ultra (550B)",
        "description": "NVIDIA flagship high-capacity reasoning model for complex architectural analysis.",
        "badge": "Flagship Reasoning"
    },
    {
        "id": "nvidia/Nemotron-3_5-Lightning",
        "name": "Nemotron 3.5 Lightning",
        "description": "High-throughput, low-latency reasoning for fast turnaround.",
        "badge": "Fast / Lightweight"
    },
    {
        "id": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
        "name": "Nemotron 3 Nano (30B)",
        "description": "Compact parameter model optimized for edge and rapid triage calls.",
        "badge": "Compact / Economy"
    }
]

@app.get("/api/engine/models")
async def list_models():
    return {
        "active_model": nebius_client.model_name,
        "models": ALLOWED_NEMOTRON_MODELS
    }

@app.post("/api/engine/model")
async def set_model(req: SetModelRequest):
    allowed_ids = [m["id"] for m in ALLOWED_NEMOTRON_MODELS]
    if req.model not in allowed_ids:
        raise HTTPException(status_code=400, detail=f"Model '{req.model}' is not in allowed Nemotron models.")
    nebius_client.model_name = req.model
    logger.info(f"Switched active Nebius inference model to {req.model}")
    return {
        "status": "success",
        "active_model": nebius_client.model_name
    }

@app.post("/api/upload")
def upload_zip(file: UploadFile = File(...), user: Optional[AuthUser] = Depends(get_optional_user)):
    if not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="Only .zip files are allowed")

    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    try:
        shutil.copyfileobj(file.file, temp_zip)
        temp_zip.close()
        ws_id = workspace_manager.create_workspace_from_zip(temp_zip.name)
        if user:
            workspace_manager.update_workspace_metadata(ws_id, {"user_id": user.id})
        return {"status": "success", "workspace_id": ws_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        if os.path.exists(temp_zip.name):
            os.remove(temp_zip.name)

@app.post("/api/benchmark/workspace")
def create_benchmark_workspace(request: BenchmarkWorkspaceRequest, user: Optional[AuthUser] = Depends(get_optional_user)):
    try:
        ws_id = workspace_manager.create_workspace_from_benchmark(request.fixture)
        if user:
            workspace_manager.update_workspace_metadata(ws_id, {"user_id": user.id})
        metadata = workspace_manager.get_workspace_metadata(ws_id)
        return {
            "status": "success",
            "workspace_id": ws_id,
            "fixture": request.fixture,
            "metadata": metadata
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/benchmarks")
def list_benchmarks():
    fixtures_dir = get_benchmark_fixtures_dir()
    benchmarks = []
    if os.path.isdir(fixtures_dir):
        for name in sorted(os.listdir(fixtures_dir)):
            full_path = os.path.join(fixtures_dir, name)
            if os.path.isdir(full_path) and not name.startswith('.'):
                benchmarks.append(name)
    return {"status": "success", "benchmarks": benchmarks}

@app.post("/api/inspect")
def inspect_repository(request: InspectRequest, user: Optional[AuthUser] = Depends(get_optional_user)):
    ws_id = request.workspace_id
    is_new_workspace = False

    try:
        if not ws_id:
            if request.benchmark:
                ws_id = workspace_manager.create_workspace_from_benchmark(request.benchmark)
                is_new_workspace = True
            elif request.repo_url:
                fixture_name = resolve_benchmark_fixture_name(request.repo_url)
                if fixture_name:
                    ws_id = workspace_manager.create_workspace_from_benchmark(fixture_name)
                else:
                    ws_id = workspace_manager.create_workspace(request.repo_url)
                is_new_workspace = True
            else:
                raise HTTPException(status_code=400, detail="Either workspace_id, benchmark, or repo_url must be provided")
            if user:
                workspace_manager.update_workspace_metadata(ws_id, {"user_id": user.id})
        else:
            verify_workspace_access(ws_id, user)

        ws_path = workspace_manager.get_workspace_path(ws_id)
        profile = RepoInspector.inspect(ws_path)

        test_result = None
        test_cmd = request.test_command or profile.detected_test_command
        if test_cmd:
            test_result = workspace_manager.run_tests(ws_id, test_cmd)

        return {
            "status": "success",
            "workspace_id": ws_id,
            "profile": profile.to_dict(),
            "test_result": test_result
        }
    except HTTPException:
        if is_new_workspace and ws_id:
            workspace_manager.cleanup_workspace(ws_id)
        raise
    except Exception as e:
        if is_new_workspace and ws_id:
            workspace_manager.cleanup_workspace(ws_id)
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/diagnose")
def diagnose(request: DiagnosisRequest, user: Optional[AuthUser] = Depends(get_optional_user)):
    ws_id = request.workspace_id
    is_new_workspace = False

    try:
        if not ws_id:
            if request.benchmark:
                ws_id = workspace_manager.create_workspace_from_benchmark(request.benchmark)
                is_new_workspace = True
            elif request.repo_url:
                fixture_name = resolve_benchmark_fixture_name(request.repo_url)
                if fixture_name:
                    ws_id = workspace_manager.create_workspace_from_benchmark(fixture_name)
                else:
                    ws_id = workspace_manager.create_workspace(request.repo_url)
                is_new_workspace = True
            else:
                raise HTTPException(status_code=400, detail="Either workspace_id, benchmark, or repo_url must be provided")
            if user:
                workspace_manager.update_workspace_metadata(ws_id, {"user_id": user.id})
        else:
            verify_workspace_access(ws_id, user)

        ws_path = workspace_manager.get_workspace_path(ws_id)
        profile = RepoInspector.inspect(ws_path)

        # Determine effective test command
        test_cmd = request.test_command or profile.detected_test_command
        repro_result = None
        if test_cmd:
            repro_result = workspace_manager.run_tests(ws_id, test_cmd)

        # Determine request intent (mode)
        mode = request.mode if request.mode and request.mode != "auto" else classify_intent(request.issue_description).intent.value

        if mode in ("bug_discovery", "improvement"):
            # Open-ended repository investigation
            bounded_context = RepoInspector.build_bounded_context(ws_path, profile=profile.to_dict(), max_total_chars=14000)
            try:
                investigation = nebius_client.investigate(
                    intent=mode,
                    issue_description=request.issue_description,
                    project_profile=profile.to_dict(),
                    code_context=bounded_context
                )
            except NebiusInferenceError as e:
                status_code = 504 if "timed out" in str(e).lower() else 502
                raise HTTPException(status_code=status_code, detail=str(e))

            findings = investigation.get("findings", [])
            primary_finding = findings[0] if findings else {}
            diagnosis_summary = {
                "fault_file": primary_finding.get("files", [""])[0] if primary_finding.get("files") else "",
                "root_cause": investigation.get("summary", ""),
                "fix_strategy": primary_finding.get("proposed_fix") or primary_finding.get("explanation") or "See recommendations",
                "confidence": primary_finding.get("confidence", "high"),
                "files_to_modify": primary_finding.get("files", [])
            }

            workspace_manager.update_workspace_metadata(
                ws_id,
                {
                    "issue_description": request.issue_description,
                    "mode": mode,
                    "profile": profile.to_dict(),
                    "investigation": investigation,
                    "findings": findings,
                    "diagnosis": diagnosis_summary,
                    "test_command": test_cmd,
                    "user_id": user.id if user else None
                }
            )

            # Persist to Supabase if authenticated user is active
            if user and supabase_manager.is_configured:
                supabase_manager.save_repair_session(
                    user_id=user.id,
                    session_data={
                        "workspace_id": ws_id,
                        "repo_url": request.repo_url or ws_path,
                        "issue_description": request.issue_description,
                        "mode": mode,
                        "status": "diagnosed",
                        "diagnosis": diagnosis_summary,
                        "findings": findings
                    }
                )

            return {
                "status": "success",
                "workspace_id": ws_id,
                "mode": mode,
                "reproduction": repro_result,
                "profile": profile.to_dict(),
                "investigation": investigation,
                "findings": findings,
                "diagnosis": diagnosis_summary
            }
        else:
            # Targeted bug repair flow
            code_context = build_context(ws_path)
            try:
                diagnosis = nebius_client.diagnose(request.issue_description, code_context)
            except NebiusInferenceError as e:
                status_code = 504 if "timed out" in str(e).lower() else 502
                raise HTTPException(status_code=status_code, detail=str(e))

            workspace_manager.update_workspace_metadata(
                ws_id,
                {
                    "issue_description": request.issue_description,
                    "mode": "targeted",
                    "profile": profile.to_dict(),
                    "diagnosis": diagnosis,
                    "test_command": test_cmd,
                    "user_id": user.id if user else None
                }
            )

            # Persist to Supabase if authenticated user is active
            if user and supabase_manager.is_configured:
                supabase_manager.save_repair_session(
                    user_id=user.id,
                    session_data={
                        "workspace_id": ws_id,
                        "repo_url": request.repo_url or ws_path,
                        "issue_description": request.issue_description,
                        "mode": "targeted",
                        "status": "diagnosed",
                        "diagnosis": diagnosis,
                        "findings": []
                    }
                )

            return {
                "status": "success",
                "workspace_id": ws_id,
                "mode": "targeted",
                "profile": profile.to_dict(),
                "reproduction": repro_result,
                "diagnosis": diagnosis
            }

    except HTTPException:
        if is_new_workspace and ws_id:
            workspace_manager.cleanup_workspace(ws_id)
        raise
    except Exception as e:
        if is_new_workspace and ws_id:
            workspace_manager.cleanup_workspace(ws_id)
        raise HTTPException(status_code=400, detail=str(e))

def resolve_targeted_test(workspace_path: str, fault_file: Optional[str]) -> Optional[str]:
    """Find the most specific test file for a given fault file to avoid full-suite timeouts."""
    if not fault_file or not workspace_path:
        return None

    clean_fault = os.path.normpath(fault_file.replace("\\", "/")).lstrip("/")
    base_name = os.path.basename(clean_fault)
    stem, _ = os.path.splitext(base_name)

    # 1. Exact repository mappings for well-known modules
    repo_mappings = {
        "main.py": "backend/tests/test_api.py",
        "app.py": "backend/tests/test_api.py",
        "github_service.py": "backend/tests/test_github.py",
        "nebius_client.py": "backend/tests/test_nebius_inference.py",
        "workspace.py": "backend/tests/test_workspace.py",
        "patch_engine.py": "backend/tests/test_patch_engine.py",
        "repo_inspector.py": "backend/tests/test_repo_inspector.py",
        "reporting.py": "backend/tests/test_reporting.py",
        "security.py": "backend/tests/test_security.py",
        "auth.py": "backend/tests/test_auth_and_persistence.py",
    }

    if base_name in repo_mappings:
        candidate = repo_mappings[base_name]
        if os.path.isfile(os.path.join(workspace_path, candidate)):
            return candidate

    # 2. Heuristic search: test_<stem>.py, <stem>_test.py in test dirs or adjacent
    search_candidates = [
        f"test_{stem}.py",
        f"{stem}_test.py",
        f"tests/test_{stem}.py",
        f"backend/tests/test_{stem}.py",
        f"test/test_{stem}.py",
    ]
    for cand in search_candidates:
        if os.path.isfile(os.path.join(workspace_path, cand)):
            return cand

    # 3. Search under tests directory for any test file containing the stem
    for test_dir in ["tests", "backend/tests", "test"]:
        abs_test_dir = os.path.join(workspace_path, test_dir)
        if os.path.isdir(abs_test_dir):
            for root, _, files in os.walk(abs_test_dir):
                for f in files:
                    if f.startswith("test_") and stem in f and f.endswith(".py"):
                        rel_path = os.path.relpath(os.path.join(root, f), workspace_path)
                        return rel_path.replace("\\", "/")

    return None

@app.post("/api/repair")
def propose_repair(request: RepairRequest, user: Optional[AuthUser] = Depends(get_optional_user)):
    ws_id = request.workspace_id
    is_new_workspace = False

    try:
        if not ws_id:
            if request.benchmark:
                ws_id = workspace_manager.create_workspace_from_benchmark(request.benchmark)
                is_new_workspace = True
            elif request.repo_url:
                fixture_name = resolve_benchmark_fixture_name(request.repo_url)
                if fixture_name:
                    ws_id = workspace_manager.create_workspace_from_benchmark(fixture_name)
                else:
                    ws_id = workspace_manager.create_workspace(request.repo_url)
                is_new_workspace = True
            else:
                raise HTTPException(status_code=400, detail="Either workspace_id, benchmark, or repo_url must be provided")
            if user:
                workspace_manager.update_workspace_metadata(ws_id, {"user_id": user.id})
        else:
            verify_workspace_access(ws_id, user)

        ws_path = workspace_manager.get_workspace_path(ws_id)

        # If a selected finding was provided instead of diagnosis_context, synthesize diagnosis_context
        if request.selected_finding and not request.diagnosis_context:
            finding = request.selected_finding
            files = finding.get("files", [])
            fault_file = files[0] if files else ""
            request.diagnosis_context = {
                "fault_file": fault_file,
                "root_cause": f"[{finding.get('title', 'Finding')}] {finding.get('explanation', '')}. Evidence: {finding.get('evidence', '')}",
                "fix_strategy": finding.get("proposed_fix") or finding.get("action") or "Apply minimal corrective patch.",
                "confidence": finding.get("confidence", "high"),
                "files_to_modify": files
            }

        focus_files = None
        if request.diagnosis_context:
            focus_files = request.diagnosis_context.get("files_to_modify")
            if not focus_files and request.diagnosis_context.get("fault_file"):
                focus_files = [request.diagnosis_context.get("fault_file")]

        ev_ctx = None
        ln_ctx = None
        if request.selected_finding:
            ev_ctx = request.selected_finding.get("evidence")
            ln_ctx = request.selected_finding.get("line_numbers")
        elif request.diagnosis_context:
            ev_ctx = request.diagnosis_context.get("evidence")
            ln_ctx = request.diagnosis_context.get("line_numbers")

        code_context = build_context(ws_path, focus_files=focus_files, evidence=ev_ctx, line_numbers=ln_ctx)

        try:
            patch = nebius_client.generate_patch(request.diagnosis_context, code_context)
        except NebiusInferenceError as e:
            workspace_manager.update_workspace_metadata(
                ws_id,
                {
                    "issue_description": request.issue_description,
                    "diagnosis_context": request.diagnosis_context,
                    "verification_status": "PATCH GENERATION FAILED",
                    "patch_applied": False,
                    "error": str(e)
                }
            )
            return {
                "status": "error",
                "message": str(e),
                "patch": "",
                "patch_applied": False,
                "verification_status": "PATCH GENERATION FAILED"
            }

        if not patch:
            workspace_manager.update_workspace_metadata(
                ws_id,
                {
                    "issue_description": request.issue_description,
                    "diagnosis_context": request.diagnosis_context,
                    "verification_status": "PATCH GENERATION FAILED",
                    "patch_applied": False
                }
            )
            return {
                "status": "error",
                "message": "Patch generation unavailable or model returned no diff",
                "patch": "",
                "patch_applied": False,
                "verification_status": "PATCH GENERATION FAILED"
            }

        target_hint = focus_files[0] if (focus_files and len(focus_files) > 0) else None
        applied = PatchEngine.apply_patch(ws_path, patch, target_file_hint=target_hint)
        if not applied:
            workspace_manager.update_workspace_metadata(
                ws_id,
                {
                    "issue_description": request.issue_description,
                    "diagnosis_context": request.diagnosis_context,
                    "patch": patch,
                    "verification_status": "APPLY FAILED",
                    "patch_applied": False
                }
            )
            return {
                "status": "error", 
                "message": "Failed to apply patch safely or unidiff validation failed",
                "patch": patch,
                "patch_applied": False,
                "verification_status": "APPLY FAILED"
            }

        verification_result = "UNVERIFIED"
        test_details = None

        # Resolve verification test command
        test_cmd = request.test_command
        if not test_cmd:
            meta = workspace_manager.get_workspace_metadata(ws_id)
            test_cmd = meta.get("test_command")

        if test_cmd:
            active_cmd = test_cmd
            if test_cmd.strip() == "pytest":
                targeted = resolve_targeted_test(ws_path, target_hint)
                if targeted:
                    active_cmd = f"pytest {targeted}"
                    logger.info(f"Targeting verification test in propose_repair: {active_cmd} for {target_hint}")
            test_details = workspace_manager.run_tests(ws_id, active_cmd)
            # returncode == -1 indicates execution failure (e.g. malformed command, disallowed base command, timeout, missing binary)
            if test_details.get("returncode") == -1:
                verification_result = "VERIFICATION INCOMPLETE"
            elif test_details.get("success") is True and test_details.get("returncode") == 0:
                verification_result = "FIX VERIFIED"
            else:
                verification_result = "FIX FAILED"

        metadata_update = {
            "issue_description": request.issue_description,
            "diagnosis_context": request.diagnosis_context,
            "patch": patch,
            "patch_applied": True,
            "verification_status": verification_result,
            "verification_details": test_details,
            "user_id": user.id if user else None
        }
        if request.selected_finding:
            metadata_update["selected_finding"] = request.selected_finding
            metadata_update["repaired_finding_id"] = str(request.selected_finding.get("id", ""))
        workspace_manager.update_workspace_metadata(ws_id, metadata_update)

        if user and supabase_manager.is_configured:
            meta = workspace_manager.get_workspace_metadata(ws_id) or {}
            supabase_manager.save_repair_session(
                user_id=user.id,
                session_data={
                    "workspace_id": ws_id,
                    "repo_url": meta.get("clone_url") or meta.get("repo_url") or request.repo_url or "",
                    "issue_description": request.issue_description or meta.get("issue_description", ""),
                    "mode": meta.get("mode", "targeted"),
                    "status": "verified" if (verification_result == "FIX VERIFIED") else "repaired",
                    "diagnosis": meta.get("diagnosis", meta.get("diagnosis_context", {})),
                    "findings": meta.get("findings", []),
                    "patch": patch,
                    "verification_status": verification_result,
                    "verification_details": test_details or {}
                }
            )

        return {
            "status": "success",
            "workspace_id": ws_id,
            "patch": patch,
            "patch_applied": True,
            "verification_status": verification_result,
            "verification_details": test_details
        }
    except HTTPException:
        if is_new_workspace and ws_id:
            workspace_manager.cleanup_workspace(ws_id)
        raise
    except Exception as e:
        if is_new_workspace and ws_id:
            workspace_manager.cleanup_workspace(ws_id)
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/rollback")
def rollback(request: RollbackRequest, user: Optional[AuthUser] = Depends(get_optional_user)):
    verify_workspace_access(request.workspace_id, user)
    success = workspace_manager.rollback_patch(request.workspace_id)
    if success:
        return {"status": "success", "message": "Rollback successful"}
    else:
        raise HTTPException(status_code=400, detail="Rollback failed")

@app.delete("/api/workspace/{workspace_id}")
def cleanup(workspace_id: str, user: Optional[AuthUser] = Depends(get_optional_user)):
    verify_workspace_access(workspace_id, user)
    workspace_manager.cleanup_workspace(workspace_id)
    return {"status": "success"}

# ---------------------------------------------------------
# GitHub Integration Endpoints
# ---------------------------------------------------------

class SaveSessionRequest(BaseModel):
    workspace_id: Optional[str] = None
    repo_url: str
    issue_description: str
    mode: Optional[str] = "targeted"
    status: Optional[str] = "completed"
    diagnosis: Optional[Dict[str, Any]] = None
    findings: Optional[List[Dict[str, Any]]] = None
    patch: Optional[str] = None
    verification_status: Optional[str] = None
    verification_details: Optional[Dict[str, Any]] = None
    pr_url: Optional[str] = None
    pr_number: Optional[int] = None
    branch: Optional[str] = None

@app.get("/api/github/status")
def github_status(user: Optional[AuthUser] = Depends(get_optional_user)):
    oauth_available = github_service.is_oauth_configured()
    
    # 1. Authenticated user path (user-scoped from Supabase)
    if user and supabase_manager.is_configured:
        conn = supabase_manager.get_github_connection(user.id)
        if not conn:
            return {
                "connected": False,
                "configured": github_service.is_configured(),
                "oauth_available": oauth_available,
                "user": None,
                "auth_type": "none",
                "account": {"id": user.id, "email": user.email}
            }
        
        # Verify active token validity with GitHub API
        try:
            token = token_encryptor.decrypt(conn["encrypted_access_token"])
            user_info = github_service.verify_token(token)
            if user_info.get("valid"):
                return {
                    "connected": True,
                    "configured": True,
                    "oauth_available": oauth_available,
                    "user": {
                        "login": user_info.get("login") or conn.get("github_login"),
                        "name": user_info.get("name") or conn.get("github_login"),
                        "avatar_url": user_info.get("avatar_url") or conn.get("avatar_url"),
                        "html_url": user_info.get("html_url") or conn.get("html_url"),
                        "scopes": user_info.get("scopes", conn.get("scopes", []))
                    },
                    "auth_type": conn.get("auth_type", "oauth"),
                    "account": {"id": user.id, "email": user.email}
                }
            else:
                return {
                    "connected": False,
                    "configured": True,
                    "oauth_available": oauth_available,
                    "user": None,
                    "auth_type": "expired",
                    "error": user_info.get("error", "GitHub token has expired or was revoked. Please reconnect."),
                    "account": {"id": user.id, "email": user.email}
                }
        except TokenEncryptionError:
            return {
                "connected": False,
                "configured": True,
                "oauth_available": oauth_available,
                "user": None,
                "auth_type": "invalid",
                "error": "Encryption key changed or token corrupted. Please reconnect.",
                "account": {"id": user.id, "email": user.email}
            }

    # 2. Guest / Demo / Test Fallback
    token = github_service.get_token()
    if not token:
        return {
            "connected": False,
            "configured": github_service.is_configured(),
            "oauth_available": oauth_available,
            "user": None,
            "auth_type": "none",
            "account": None
        }
    user_info = github_service.verify_token(token)
    if user_info.get("valid"):
        return {
            "connected": True,
            "configured": True,
            "oauth_available": oauth_available,
            "user": {
                "login": user_info.get("login"),
                "name": user_info.get("name"),
                "avatar_url": user_info.get("avatar_url"),
                "html_url": user_info.get("html_url"),
                "scopes": user_info.get("scopes", [])
            },
            "auth_type": "pat",
            "account": None
        }
    else:
        return {
            "connected": False,
            "configured": True,
            "oauth_available": oauth_available,
            "user": None,
            "auth_type": "invalid",
            "error": user_info.get("error", "Invalid or expired token"),
            "account": None
        }

@app.get("/api/github/oauth/url")
def github_oauth_url(redirect_uri: Optional[str] = None, user: Optional[AuthUser] = Depends(get_optional_user)):
    if not github_service.is_oauth_configured():
        raise HTTPException(status_code=400, detail="GitHub OAuth is not configured on the server")
    url = github_service.get_oauth_url(redirect_uri=redirect_uri, user_id=user.id if user else None)
    return {"url": url}

@app.get("/api/github/oauth/callback")
def github_oauth_callback(code: str, state: str, redirect_uri: Optional[str] = None):
    state_data = github_service.pop_oauth_state(state)
    if not state_data:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state parameter")

    success, token, err = github_service.exchange_oauth_code(code, redirect_uri=redirect_uri)
    if not success or not token:
        raise HTTPException(status_code=400, detail=err or "Failed to exchange OAuth code for access token")

    user_info = github_service.verify_token(token)
    if not user_info.get("valid"):
        raise HTTPException(status_code=400, detail=user_info.get("error", "Failed to verify token with GitHub"))

    user_id = state_data.get("user_id")
    if user_id and supabase_manager.is_configured:
        try:
            encrypted_token = token_encryptor.encrypt(token)
            supabase_manager.save_github_connection(
                user_id=user_id,
                github_user_id=str(user_info.get("id", "")),
                github_login=user_info.get("login", ""),
                encrypted_token=encrypted_token,
                avatar_url=user_info.get("avatar_url"),
                html_url=user_info.get("html_url"),
                scopes=user_info.get("scopes", []),
                auth_type="oauth"
            )
        except Exception as e:
            logger.error(f"Failed to persist OAuth connection in Supabase: {e}")
            raise HTTPException(status_code=500, detail="Failed to persist encrypted GitHub credentials.")
    else:
        github_service.set_session_token(token)

    return RedirectResponse(url="/?github_connected=true", status_code=303)

@app.post("/api/github/connect")
def github_connect(request: GitHubConnectRequest, user: Optional[AuthUser] = Depends(get_optional_user)):
    token = request.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Token cannot be empty")
    
    user_info = github_service.verify_token(token)
    if not user_info.get("valid"):
        raise HTTPException(status_code=400, detail=user_info.get("error", "Invalid or expired GitHub credentials"))
    
    if user and supabase_manager.is_configured:
        try:
            encrypted_token = token_encryptor.encrypt(token)
            supabase_manager.save_github_connection(
                user_id=user.id,
                github_user_id=str(user_info.get("id", "")),
                github_login=user_info.get("login", ""),
                encrypted_token=encrypted_token,
                avatar_url=user_info.get("avatar_url"),
                html_url=user_info.get("html_url"),
                scopes=user_info.get("scopes", []),
                auth_type="pat"
            )
        except Exception as e:
            logger.error(f"Failed to persist PAT connection in Supabase: {e}")
            raise HTTPException(status_code=500, detail="Failed to persist encrypted GitHub credentials.")
    else:
        github_service.set_session_token(token)

    return {
        "status": "connected",
        "connected": True,
        "user": {
            "login": user_info.get("login"),
            "name": user_info.get("name"),
            "avatar_url": user_info.get("avatar_url"),
            "html_url": user_info.get("html_url"),
            "scopes": user_info.get("scopes", [])
        }
    }

@app.post("/api/github/disconnect")
def github_disconnect(user: Optional[AuthUser] = Depends(get_optional_user)):
    if user and supabase_manager.is_configured:
        supabase_manager.delete_github_connection(user.id)
    github_service.set_session_token(None)
    return {"status": "disconnected"}

@app.get("/api/github/repos")
def github_repos(q: Optional[str] = None, page: int = 1, user: Optional[AuthUser] = Depends(get_optional_user)):
    token = resolve_github_token(user)
    if not token:
        raise HTTPException(status_code=401, detail="GitHub not connected. Please connect your GitHub account.")
    
    repos = github_service.list_repositories(token, query=q, page=page)
    return {"repos": repos}

@app.get("/api/github/repos/{owner}/{repo}/branches")
def github_branches(owner: str, repo: str, user: Optional[AuthUser] = Depends(get_optional_user)):
    token = resolve_github_token(user)
    if not token:
        raise HTTPException(status_code=401, detail="GitHub not connected. Please connect your GitHub account.")
    
    if not REPO_NAME_REGEX.match(owner) or not REPO_NAME_REGEX.match(repo):
        raise HTTPException(status_code=400, detail="Invalid owner or repository name format")
        
    branches = github_service.list_branches(token, owner, repo)
    return {"branches": branches}

@app.post("/api/github/workspace")
def create_github_workspace(request: GitHubWorkspaceRequest, user: Optional[AuthUser] = Depends(get_optional_user)):
    token = resolve_github_token(user, request.token)
    if not token:
        raise HTTPException(status_code=401, detail="GitHub not connected. Please connect your GitHub account.")
        
    owner = request.owner.strip()
    repo = request.repo.strip()
    branch = request.branch.strip()
    
    if not REPO_NAME_REGEX.match(owner) or not REPO_NAME_REGEX.match(repo):
        raise HTTPException(status_code=400, detail="Invalid owner or repository name format")
        
    ws_id = os.urandom(8).hex()
    ws_path = os.path.join(workspace_manager.base_dir, f"proofpatch_ws_{ws_id}")
    
    try:
        commit_sha = github_service.clone_github_repo(token, owner, repo, branch, ws_path)
        workspace_manager.register_workspace(
            workspace_id=ws_id,
            workspace_path=ws_path,
            metadata={
                "source_type": "github",
                "owner": owner,
                "repo": repo,
                "target_branch": branch,
                "starting_commit_sha": commit_sha,
                "clone_url": f"https://github.com/{owner}/{repo}.git",
                "user_id": user.id if user else None
            }
        )
        return {
            "status": "success",
            "workspace_id": ws_id,
            "owner": owner,
            "repo": repo,
            "branch": branch,
            "starting_commit_sha": commit_sha
        }
    except Exception as e:
        if os.path.exists(ws_path):
            shutil.rmtree(ws_path)
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/github/publish/readiness")
def github_publish_readiness(workspace_id: str, user: Optional[AuthUser] = Depends(get_optional_user)):
    verify_workspace_access(workspace_id, user)
    meta = workspace_manager.get_workspace_metadata(workspace_id)
    if not meta or meta.get("source_type") != "github":
        return {
            "ready": False,
            "reason": "Workspace is not linked to a GitHub repository",
            "verification_status": meta.get("verification_status", "UNVERIFIED")
        }
        
    verification_status = meta.get("verification_status", "UNVERIFIED")
    token = resolve_github_token(user)
    
    diverged = False
    remote_sha = None
    if token and meta.get("starting_commit_sha"):
        try:
            diverged, remote_sha = github_service.check_divergence(
                token,
                meta["owner"],
                meta["repo"],
                meta["target_branch"],
                meta["starting_commit_sha"]
            )
        except Exception:
            pass
            
    ready = (verification_status == "FIX VERIFIED") and not diverged
    reason = None
    existing_pr = None

    if verification_status != "FIX VERIFIED":
        reason = f"Verification is {verification_status}. Only 'FIX VERIFIED' patches can be published."
    elif diverged:
        reason = f"Target branch '{meta['target_branch']}' has diverged on remote."

    # Prevent duplicate PRs: check if an open or merged PR already exists for this repair
    if token and meta.get("owner") and meta.get("repo"):
        try:
            prs = github_service.list_repository_pull_requests(token, meta["owner"], meta["repo"], state="all")
            findings_to_check = []
            if meta.get("selected_finding"):
                findings_to_check = [meta["selected_finding"]]
            elif meta.get("batch_repaired_findings"):
                findings_to_check = meta["batch_repaired_findings"]
            elif meta.get("findings"):
                findings_to_check = meta["findings"]

            matched = github_service.match_findings_to_pull_requests(findings_to_check, prs, workspace_meta=meta)
            for m in matched.values():
                if m.get("confidence") in ("exact_fingerprint", "session_link"):
                    if m.get("is_merged"):
                        existing_pr = m
                        ready = False
                        reason = f"A pull request (#{m.get('pr_number')}) for this repair has already been merged: {m.get('pr_url')}"
                        break
                    elif m.get("is_open"):
                        existing_pr = m
                        ready = False
                        reason = f"A pull request (#{m.get('pr_number')}) has already been submitted for this repair: {m.get('pr_url')}"
                        break
        except Exception as e:
            logger.warning(f"Could not verify existing PRs in readiness: {e}")

    return {
        "ready": ready,
        "verification_status": verification_status,
        "diverged": diverged,
        "starting_commit_sha": meta.get("starting_commit_sha"),
        "remote_commit_sha": remote_sha,
        "owner": meta.get("owner"),
        "repo": meta.get("repo"),
        "target_branch": meta.get("target_branch"),
        "published_pr": meta.get("published_pr"),
        "existing_pr": existing_pr,
        "reason": reason
    }

@app.post("/api/github/publish")
def github_publish(request: GitHubPublishRequest, user: Optional[AuthUser] = Depends(get_optional_user)):
    verify_workspace_access(request.workspace_id, user)
    meta = workspace_manager.get_workspace_metadata(request.workspace_id)
    if not meta or meta.get("source_type") != "github":
        raise HTTPException(status_code=400, detail="Workspace is not a valid GitHub repository workspace.")
        
    # Revalidate verification gate on backend immediately before publication
    verification_status = meta.get("verification_status", "UNVERIFIED")
    if verification_status != "FIX VERIFIED":
        raise HTTPException(
            status_code=400,
            detail=f"Publication gate blocked: Workspace verification status is '{verification_status}', but only 'FIX VERIFIED' patches may be published."
        )
        
    token = resolve_github_token(user, request.token)
    if not token:
        raise HTTPException(status_code=401, detail="GitHub credentials not found. Please connect your GitHub account.")
        
    try:
        ws_path = workspace_manager.get_workspace_path(request.workspace_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
        
    # Check remote branch divergence
    diverged, remote_sha = github_service.check_divergence(
        token,
        meta["owner"],
        meta["repo"],
        meta["target_branch"],
        meta["starting_commit_sha"]
    )
    if diverged:
        raise HTTPException(
            status_code=409,
            detail=f"Target branch '{meta['target_branch']}' has diverged on remote. Current SHA: {remote_sha[:8] if remote_sha else 'unknown'}. Publication aborted to prevent conflicts."
        )

    # Check for existing PR: prevent duplicate publication if confidently matched
    if meta.get("owner") and meta.get("repo"):
        try:
            prs = github_service.list_repository_pull_requests(token, meta["owner"], meta["repo"], state="all")
            findings_to_check = []
            if meta.get("selected_finding"):
                findings_to_check = [meta["selected_finding"]]
            elif meta.get("batch_repaired_findings"):
                findings_to_check = meta["batch_repaired_findings"]
            elif meta.get("findings"):
                findings_to_check = meta["findings"]

            matched = github_service.match_findings_to_pull_requests(findings_to_check, prs, workspace_meta=meta)
            for m in matched.values():
                if m.get("confidence") in ("exact_fingerprint", "session_link"):
                    if m.get("is_merged") or m.get("is_open"):
                        st_desc = "merged" if m.get("is_merged") else "already open"
                        raise HTTPException(
                            status_code=409,
                            detail=f"Duplicate PR prevented: Pull request #{m.get('pr_number')} is {st_desc} for this repair ({m.get('pr_url')})."
                        )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Could not verify existing PRs before publishing: {e}")
        
    title = request.title or meta.get("issue_description") or "Resolve defect in target repository"
    if len(title) > 80:
        title = title[:77] + "..."

    # Gather fingerprints and finding IDs for machine-readable traceability
    finding_fingerprints: List[str] = []
    finding_ids: List[str] = []
    if meta.get("selected_finding"):
        sf = meta["selected_finding"]
        finding_fingerprints.append(compute_finding_fingerprint(sf))
        if "id" in sf:
            finding_ids.append(str(sf["id"]))
    elif meta.get("batch_repaired_findings"):
        for bf in meta["batch_repaired_findings"]:
            finding_fingerprints.append(compute_finding_fingerprint(bf))
            if "id" in bf:
                finding_ids.append(str(bf["id"]))
    elif meta.get("findings"):
        for f in meta["findings"]:
            finding_fingerprints.append(compute_finding_fingerprint(f))
            if "id" in f:
                finding_ids.append(str(f["id"]))
        
    try:
        pr_result = github_service.publish_pull_request(
            token=token,
            owner=meta["owner"],
            repo=meta["repo"],
            target_branch=meta["target_branch"],
            starting_sha=meta["starting_commit_sha"],
            workspace_path=ws_path,
            workspace_id=request.workspace_id,
            title=title,
            problem_summary=meta.get("issue_description", "Resolve defect in codebase"),
            diagnosis_data=meta.get("diagnosis", meta.get("diagnosis_context", {})),
            verification_details=meta.get("verification_details"),
            model_name=nebius_client.model_name,
            is_mock_mode=nebius_client.mock_mode,
            custom_notes=request.custom_notes,
            finding_fingerprints=finding_fingerprints,
            finding_ids=finding_ids
        )
        meta["published_pr"] = pr_result
        workspace_manager.update_workspace_metadata(request.workspace_id, meta)

        # Update or record in repair_sessions table if user is authenticated
        if user and supabase_manager.is_configured:
            supabase_manager.save_repair_session(
                user_id=user.id,
                session_data={
                    "workspace_id": request.workspace_id,
                    "repo_url": meta.get("clone_url") or f"https://github.com/{meta['owner']}/{meta['repo']}",
                    "issue_description": meta.get("issue_description", ""),
                    "mode": meta.get("mode", "targeted"),
                    "status": "published",
                    "diagnosis": meta.get("diagnosis", {}),
                    "findings": meta.get("findings", []),
                    "patch": meta.get("patch", ""),
                    "verification_status": verification_status,
                    "verification_details": meta.get("verification_details", {}),
                    "pr_url": pr_result.get("pr_url"),
                    "pr_number": pr_result.get("pr_number"),
                    "branch": pr_result.get("branch")
                }
            )

        return pr_result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/github/findings/status")
def github_findings_status(workspace_id: str, user: Optional[AuthUser] = Depends(get_optional_user)):
    """
    Live query repository pull requests and match against workspace findings.
    Returns structured status (PR OPEN, MERGED, PR CLOSED, POSSIBLE EXISTING PR, READY, or STATUS UNKNOWN).
    Scoped strictly to repository and authenticated user.
    """
    verify_workspace_access(workspace_id, user)
    meta = workspace_manager.get_workspace_metadata(workspace_id) or {}
    findings = meta.get("findings", [])
    if not findings and meta.get("selected_finding"):
        findings = [meta["selected_finding"]]

    owner = meta.get("owner")
    repo = meta.get("repo")
    is_github = (meta.get("source_type") == "github") or bool(owner and repo)

    if not is_github or not owner or not repo:
        return {
            "status": "not_linked",
            "github_connected": False,
            "repository": None,
            "findings": {
                str(f.get("id")): {
                    "finding_id": str(f.get("id")),
                    "fingerprint": compute_finding_fingerprint(f),
                    "lifecycle_status": "ready",
                    "badge_status": "READY",
                    "pr_number": None,
                    "pr_url": None,
                    "confidence": "none",
                    "is_merged": False,
                    "is_open": False,
                    "is_eligible_for_repair": True,
                    "ineligibility_reason": None
                }
                for f in findings if "id" in f
            }
        }

    token = resolve_github_token(user)
    if not token:
        return {
            "status": "error",
            "github_connected": False,
            "repository": f"{owner}/{repo}",
            "error": "GitHub credentials not found or disconnected",
            "findings": {
                str(f.get("id")): {
                    "finding_id": str(f.get("id")),
                    "fingerprint": compute_finding_fingerprint(f),
                    "lifecycle_status": "status_unknown",
                    "badge_status": "STATUS UNKNOWN",
                    "pr_number": None,
                    "pr_url": None,
                    "confidence": "none",
                    "is_merged": False,
                    "is_open": False,
                    "is_eligible_for_repair": True,
                    "ineligibility_reason": "GitHub is not connected"
                }
                for f in findings if "id" in f
            }
        }

    try:
        prs = github_service.list_repository_pull_requests(token, owner, repo, state="all")
    except Exception as e:
        logger.warning(f"Failed to query GitHub PRs for findings status: {e}")
        return {
            "status": "error",
            "github_connected": True,
            "repository": f"{owner}/{repo}",
            "error": str(e),
            "findings": {
                str(f.get("id")): {
                    "finding_id": str(f.get("id")),
                    "fingerprint": compute_finding_fingerprint(f),
                    "lifecycle_status": "status_unknown",
                    "badge_status": "STATUS UNKNOWN",
                    "pr_number": None,
                    "pr_url": None,
                    "confidence": "none",
                    "is_merged": False,
                    "is_open": False,
                    "is_eligible_for_repair": True,
                    "ineligibility_reason": f"GitHub API error: {str(e)}"
                }
                for f in findings if "id" in f
            }
        }

    repair_sessions: List[Dict[str, Any]] = []
    if user and supabase_manager.is_configured:
        try:
            repair_sessions = supabase_manager.list_repair_sessions(user.id, limit=30)
        except Exception as e:
            logger.warning(f"Could not load repair sessions for user {user.id}: {e}")

    matched = github_service.match_findings_to_pull_requests(
        findings=findings,
        pull_requests=prs,
        workspace_meta=meta,
        repair_sessions=repair_sessions
    )

    return {
        "status": "success",
        "github_connected": True,
        "repository": f"{owner}/{repo}",
        "findings": matched
    }

@app.post("/api/repair/batch")
def batch_repair(request: BatchRepairRequest, user: Optional[AuthUser] = Depends(get_optional_user)):
    """
    Safely execute batch repair across multiple findings:
    - Serialized execution to avoid conflicting modifications
    - Checkpoint and automatic rollback if an individual patch or verification test fails
    - Per-finding results and cumulative diff
    - Verification safeguards maintained
    - Batch repair and PR publishing remain separate actions
    """
    verify_workspace_access(request.workspace_id, user)
    try:
        ws_path = workspace_manager.get_workspace_path(request.workspace_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    meta = workspace_manager.get_workspace_metadata(request.workspace_id) or {}
    all_findings = meta.get("findings", [])
    findings_by_id = {str(f.get("id")): f for f in all_findings if "id" in f}

    if not request.finding_ids:
        raise HTTPException(status_code=400, detail="No finding IDs provided for batch repair.")

    # Check PR status & eligibility to prevent repairing already submitted or merged findings
    token = resolve_github_token(user)
    pr_status_map: Dict[str, Dict[str, Any]] = {}
    if token and meta.get("owner") and meta.get("repo"):
        try:
            prs = github_service.list_repository_pull_requests(token, meta["owner"], meta["repo"], state="all")
            pr_status_map = github_service.match_findings_to_pull_requests(all_findings, prs, workspace_meta=meta)
        except Exception as e:
            logger.warning(f"PR status check skipped or failed in batch repair: {e}")

    test_cmd = request.test_command or meta.get("test_command")

    # Initialize repository
    try:
        repo = Repo(ws_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Workspace is not a valid git repository: {e}")

    # Checkpoint any pre-existing uncommitted or untracked changes to prevent rollback from discarding them
    if repo.is_dirty(untracked_files=True):
        repo.git.add("-A")
        repo.index.commit("chore: checkpoint workspace state prior to batch repair")

    initial_sha = repo.head.commit.hexsha
    results: List[Dict[str, Any]] = []
    successful_findings: List[Dict[str, Any]] = []

    for fid in request.finding_ids:
        fid_str = str(fid)
        if fid_str not in findings_by_id:
            results.append({
                "finding_id": fid_str,
                "title": f"Finding {fid_str}",
                "status": "failed",
                "verification_status": "NOT_FOUND",
                "error": f"Finding '{fid_str}' not found in workspace findings.",
                "patch": "",
                "test_details": None
            })
            continue

        finding = findings_by_id[fid_str]
        title = finding.get("title", f"Finding {fid_str}")

        # Check eligibility against PR status
        pr_info = pr_status_map.get(fid_str)
        if pr_info and not pr_info.get("is_eligible_for_repair", True):
            results.append({
                "finding_id": fid_str,
                "title": title,
                "status": "skipped",
                "verification_status": "SKIPPED",
                "error": pr_info.get("ineligibility_reason") or "Finding is not eligible for repair (already submitted or merged).",
                "patch": "",
                "test_details": None
            })
            continue

        # Checkpoint current git state before attempting patch
        checkpoint_sha = repo.head.commit.hexsha

        # Synthesize diagnosis context
        files = finding.get("files", [])
        fault_file = files[0] if files else ""
        diag_ctx = {
            "fault_file": fault_file,
            "root_cause": f"[{title}] {finding.get('explanation', '')}. Evidence: {finding.get('evidence', '')}",
            "fix_strategy": finding.get("proposed_fix") or finding.get("action") or "Apply minimal corrective patch.",
            "confidence": finding.get("confidence", "high"),
            "files_to_modify": files
        }

        # Build fresh code context (takes into account previous successful repairs)
        focus_files = files if files else ([fault_file] if fault_file else None)
        code_ctx = build_context(
            ws_path,
            focus_files=focus_files,
            evidence=finding.get("evidence"),
            line_numbers=finding.get("line_numbers")
        )

        # Generate patch
        try:
            patch = nebius_client.generate_patch(diag_ctx, code_ctx)
        except Exception as e:
            repo.git.reset("--hard", checkpoint_sha)
            repo.git.clean("-fd")
            results.append({
                "finding_id": fid_str,
                "title": title,
                "status": "failed",
                "verification_status": "PATCH GENERATION FAILED",
                "error": f"Patch synthesis failed: {str(e)}",
                "patch": "",
                "test_details": None
            })
            continue

        if not patch:
            repo.git.reset("--hard", checkpoint_sha)
            repo.git.clean("-fd")
            results.append({
                "finding_id": fid_str,
                "title": title,
                "status": "failed",
                "verification_status": "PATCH GENERATION FAILED",
                "error": "Model returned an empty patch.",
                "patch": "",
                "test_details": None
            })
            continue

        # Safely apply patch
        applied = PatchEngine.apply_patch(ws_path, patch, target_file_hint=fault_file)
        if not applied:
            repo.git.reset("--hard", checkpoint_sha)
            repo.git.clean("-fd")
            results.append({
                "finding_id": fid_str,
                "title": title,
                "status": "failed",
                "verification_status": "APPLY FAILED",
                "error": "Failed to apply patch cleanly or unidiff validation failed.",
                "patch": patch,
                "test_details": None
            })
            continue

        # Run verification tests
        test_details = None
        verification_status = "UNVERIFIED"
        if test_cmd:
            active_cmd = test_cmd
            if test_cmd.strip() == "pytest":
                targeted = resolve_targeted_test(ws_path, fault_file)
                if targeted:
                    active_cmd = f"pytest {targeted}"
                    logger.info(f"Targeting verification test in batch repair: {active_cmd} for {fault_file}")

            test_details = workspace_manager.run_tests(request.workspace_id, active_cmd)
            if test_details.get("returncode") == 0 and test_details.get("success") is True:
                verification_status = "FIX VERIFIED"
            elif test_details.get("returncode") == -1:
                verification_status = "VERIFICATION INCOMPLETE"
            else:
                verification_status = "FIX FAILED"

        # If tests failed, rollback this finding
        if test_cmd and verification_status != "FIX VERIFIED":
            repo.git.reset("--hard", checkpoint_sha)
            repo.git.clean("-fd")
            results.append({
                "finding_id": fid_str,
                "title": title,
                "status": "rolled_back",
                "verification_status": verification_status,
                "error": f"Verification failed with exit code {test_details.get('returncode')}. Patch safely rolled back.",
                "patch": patch,
                "test_details": test_details
            })
            continue

        # Commit clean fix to repo
        clean_msg = format_commit_title(f"fix: {title}")
        repo.git.add("-A")
        repo.index.commit(clean_msg)
        new_sha = repo.head.commit.hexsha

        successful_findings.append(finding)
        results.append({
            "finding_id": fid_str,
            "title": title,
            "status": "verified" if verification_status == "FIX VERIFIED" else "repaired",
            "verification_status": verification_status,
            "patch": patch,
            "commit_sha": new_sha,
            "test_details": test_details
        })

    # Cumulative diff from initial SHA to current HEAD
    try:
        cumulative_diff = repo.git.diff(initial_sha, repo.head.commit.hexsha)
    except Exception:
        cumulative_diff = ""

    num_total = len(request.finding_ids)
    num_successful = sum(1 for r in results if r["status"] in ("verified", "repaired"))
    num_failed = sum(1 for r in results if r["status"] in ("failed", "rolled_back"))
    num_skipped = sum(1 for r in results if r["status"] == "skipped")

    all_succeeded = (num_successful == num_total) and (num_failed == 0) and (num_skipped == 0)
    batch_status = "success" if all_succeeded else ("partial_success" if num_successful > 0 else "failed")
    overall_verification = "FIX VERIFIED" if (all_succeeded and test_cmd) else ("PARTIAL FIX" if num_successful > 0 else "FIX FAILED")

    workspace_manager.update_workspace_metadata(
        request.workspace_id,
        {
            "batch_results": results,
            "batch_repaired_findings": successful_findings,
            "batch_repaired_finding_ids": [r["finding_id"] for r in results if r["status"] in ("verified", "repaired")],
            "patch": cumulative_diff,
            "patch_applied": num_successful > 0,
            "verification_status": overall_verification,
            "user_id": user.id if user else None
        }
    )

    if user and supabase_manager.is_configured and num_successful > 0:
        supabase_manager.save_repair_session(
            user_id=user.id,
            session_data={
                "workspace_id": request.workspace_id,
                "repo_url": meta.get("clone_url") or meta.get("repo_url") or "",
                "issue_description": f"Batch repair: {num_successful}/{num_total} findings resolved",
                "mode": "batch",
                "status": "verified" if all_succeeded else "partial",
                "findings": successful_findings,
                "patch": cumulative_diff,
                "verification_status": overall_verification,
                "verification_details": {"batch_summary": {"total": num_total, "successful": num_successful, "failed": num_failed, "skipped": num_skipped}}
            }
        )

    return {
        "status": batch_status,
        "all_succeeded": all_succeeded,
        "summary": {
            "total": num_total,
            "successful": num_successful,
            "failed": num_failed,
            "skipped": num_skipped
        },
        "results": results,
        "cumulative_patch": cumulative_diff
    }

# ---------------------------------------------------------
# User Repair History Endpoints
# ---------------------------------------------------------

@app.get("/api/history")
def get_repair_history(limit: int = 20, user: AuthUser = Depends(get_current_user)):
    """Fetch persistent repair history scoped strictly to the authenticated user."""
    sessions = supabase_manager.list_repair_sessions(user.id, limit=limit)
    return {"status": "success", "sessions": sessions}

@app.post("/api/history")
def save_repair_history(request: SaveSessionRequest, user: AuthUser = Depends(get_current_user)):
    """Save or synchronize a repair session to persistent storage."""
    session_data = request.model_dump() if hasattr(request, "model_dump") else request.dict()
    session_id = supabase_manager.save_repair_session(user.id, session_data)
    return {"status": "success", "session_id": session_id}

@app.delete("/api/history/{session_id}")
def delete_repair_history(session_id: str, user: AuthUser = Depends(get_current_user)):
    """Delete a repair session strictly owned by the authenticated user."""
    success = supabase_manager.delete_repair_session(user.id, session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Repair session not found or access denied")
    return {"status": "success"}

# ---------------------------------------------------------
# Static Frontend Serving (Single-Service Production Mode)
# ---------------------------------------------------------
frontend_dist = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"))
if os.path.exists(frontend_dist):
    assets_dir = os.path.join(frontend_dist, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="static-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str):
        if full_path.startswith("api/") or full_path in ("docs", "redoc", "openapi.json"):
            raise HTTPException(status_code=404, detail="Not Found")
        target_file = os.path.join(frontend_dist, full_path)
        if full_path and os.path.isfile(target_file):
            return FileResponse(target_file)
        index_file = os.path.join(frontend_dist, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        raise HTTPException(status_code=404, detail="Frontend index.html not found")



