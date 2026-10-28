from fastapi import FastAPI, APIRouter, HTTPException, BackgroundTasks, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
import os
import shutil
import tempfile
from typing import Optional, List, Dict, Any
import re
from .workspace import WorkspaceManager, get_benchmark_fixtures_dir, resolve_benchmark_fixture_name
from .patch_engine import PatchEngine
from .nebius_client import NebiusClient, NebiusInferenceError
from .github_service import GitHubService, REPO_NAME_REGEX, sanitize_branch_name
from .intent_classifier import classify_intent, RequestIntent
from .repo_inspector import RepoInspector, IGNORE_DIRS, IGNORE_EXTS

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

def build_context(ws_path: str, focus_files: Optional[List[str]] = None) -> str:
    code_context = ""
    # If focus files provided, prioritize them
    if focus_files:
        for f in focus_files:
            target = os.path.join(ws_path, f)
            if os.path.isfile(target):
                try:
                    with open(target, 'r', errors='ignore') as fh:
                        content = fh.read()
                        if len(content) > 8000:
                            content = content[:8000] + "\n... [truncated]"
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
        "model": nebius_client.model_name
    }

@app.post("/api/upload")
async def upload_zip(file: UploadFile = File(...)):
    if not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="Only .zip files are allowed")

    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    try:
        shutil.copyfileobj(file.file, temp_zip)
        temp_zip.close()
        ws_id = workspace_manager.create_workspace_from_zip(temp_zip.name)
        return {"status": "success", "workspace_id": ws_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        if os.path.exists(temp_zip.name):
            os.remove(temp_zip.name)

@app.post("/api/benchmark/workspace")
async def create_benchmark_workspace(request: BenchmarkWorkspaceRequest):
    try:
        ws_id = workspace_manager.create_workspace_from_benchmark(request.fixture)
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
async def list_benchmarks():
    fixtures_dir = get_benchmark_fixtures_dir()
    benchmarks = []
    if os.path.isdir(fixtures_dir):
        for name in sorted(os.listdir(fixtures_dir)):
            full_path = os.path.join(fixtures_dir, name)
            if os.path.isdir(full_path) and not name.startswith('.'):
                benchmarks.append(name)
    return {"status": "success", "benchmarks": benchmarks}

@app.post("/api/inspect")
async def inspect_repository(request: InspectRequest):
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
    except Exception as e:
        if is_new_workspace and ws_id:
            workspace_manager.cleanup_workspace(ws_id)
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/diagnose")
async def diagnose(request: DiagnosisRequest):
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
            bounded_context = RepoInspector.build_bounded_context(ws_path, max_total_chars=18000)
            try:
                investigation = nebius_client.investigate(
                    intent=mode,
                    issue_description=request.issue_description,
                    project_profile=profile.to_dict(),
                    code_context=bounded_context
                )
            except NebiusInferenceError as e:
                raise HTTPException(status_code=502, detail=str(e))

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
                    "test_command": test_cmd
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
                raise HTTPException(status_code=502, detail=str(e))

            workspace_manager.update_workspace_metadata(
                ws_id,
                {
                    "issue_description": request.issue_description,
                    "mode": "targeted",
                    "profile": profile.to_dict(),
                    "diagnosis": diagnosis,
                    "test_command": test_cmd
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

@app.post("/api/repair")
async def propose_repair(request: RepairRequest):
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

        code_context = build_context(ws_path, focus_files=focus_files)

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

        applied = PatchEngine.apply_patch(ws_path, patch)
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
            test_details = workspace_manager.run_tests(ws_id, test_cmd)
            # returncode == -1 indicates execution failure (e.g. malformed command, disallowed base command, timeout, missing binary)
            if test_details.get("returncode") == -1:
                verification_result = "VERIFICATION INCOMPLETE"
            elif test_details.get("success") is True and test_details.get("returncode") == 0:
                verification_result = "FIX VERIFIED"
            else:
                verification_result = "FIX FAILED"

        workspace_manager.update_workspace_metadata(
            ws_id,
            {
                "issue_description": request.issue_description,
                "diagnosis_context": request.diagnosis_context,
                "patch": patch,
                "patch_applied": True,
                "verification_status": verification_result,
                "verification_details": test_details
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
    except Exception as e:
        if is_new_workspace and ws_id:
            workspace_manager.cleanup_workspace(ws_id)
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/rollback")
async def rollback(request: RollbackRequest):
    success = workspace_manager.rollback_patch(request.workspace_id)
    if success:
        return {"status": "success", "message": "Rollback successful"}
    else:
        raise HTTPException(status_code=400, detail="Rollback failed")

@app.delete("/api/workspace/{workspace_id}")
async def cleanup(workspace_id: str):
    workspace_manager.cleanup_workspace(workspace_id)
    return {"status": "success"}

# ---------------------------------------------------------
# GitHub Integration Endpoints
# ---------------------------------------------------------

@app.get("/api/github/status")
async def github_status():
    token = github_service.get_token()
    oauth_available = github_service.is_oauth_configured()
    if not token:
        return {
            "connected": False,
            "configured": github_service.is_configured(),
            "oauth_available": oauth_available,
            "user": None,
            "auth_type": "none"
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
            "auth_type": "pat"
        }
    else:
        return {
            "connected": False,
            "configured": True,
            "oauth_available": oauth_available,
            "user": None,
            "auth_type": "invalid",
            "error": user_info.get("error", "Invalid or expired token")
        }

@app.get("/api/github/oauth/url")
async def github_oauth_url(redirect_uri: Optional[str] = None):
    if not github_service.is_oauth_configured():
        raise HTTPException(status_code=400, detail="GitHub OAuth is not configured on the server")
    url = github_service.get_oauth_url(redirect_uri=redirect_uri)
    return {"url": url}

@app.get("/api/github/oauth/callback")
async def github_oauth_callback(code: str, state: str, redirect_uri: Optional[str] = None):
    if not github_service.validate_oauth_state(state):
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state parameter")

    success, token, err = github_service.exchange_oauth_code(code, redirect_uri=redirect_uri)
    if not success or not token:
        raise HTTPException(status_code=400, detail=err or "Failed to exchange OAuth code for access token")

    user_info = github_service.verify_token(token)
    if not user_info.get("valid"):
        raise HTTPException(status_code=400, detail=user_info.get("error", "Failed to verify token with GitHub"))

    github_service.set_session_token(token)
    return RedirectResponse(url="/?github_connected=true", status_code=303)

@app.post("/api/github/connect")
async def github_connect(request: GitHubConnectRequest):
    token = request.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Token cannot be empty")
    
    user_info = github_service.verify_token(token)
    if not user_info.get("valid"):
        raise HTTPException(status_code=400, detail=user_info.get("error", "Invalid or expired GitHub credentials"))
    
    github_service.set_session_token(token)
    return {
        "status": "connected",
        "user": {
            "login": user_info.get("login"),
            "name": user_info.get("name"),
            "avatar_url": user_info.get("avatar_url"),
            "html_url": user_info.get("html_url"),
            "scopes": user_info.get("scopes", [])
        }
    }

@app.post("/api/github/disconnect")
async def github_disconnect():
    github_service.set_session_token(None)
    return {"status": "disconnected"}

@app.get("/api/github/repos")
async def github_repos(q: Optional[str] = None, page: int = 1):
    token = github_service.get_token()
    if not token:
        raise HTTPException(status_code=401, detail="GitHub not connected. Please connect your GitHub account.")
    
    repos = github_service.list_repositories(token, query=q, page=page)
    return {"repos": repos}

@app.get("/api/github/repos/{owner}/{repo}/branches")
async def github_branches(owner: str, repo: str):
    token = github_service.get_token()
    if not token:
        raise HTTPException(status_code=401, detail="GitHub not connected. Please connect your GitHub account.")
    
    if not REPO_NAME_REGEX.match(owner) or not REPO_NAME_REGEX.match(repo):
        raise HTTPException(status_code=400, detail="Invalid owner or repository name format")
        
    branches = github_service.list_branches(token, owner, repo)
    return {"branches": branches}

@app.post("/api/github/workspace")
async def create_github_workspace(request: GitHubWorkspaceRequest):
    token = github_service.get_token(request.token)
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
                "clone_url": f"https://github.com/{owner}/{repo}.git"
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
async def github_publish_readiness(workspace_id: str):
    meta = workspace_manager.get_workspace_metadata(workspace_id)
    if not meta or meta.get("source_type") != "github":
        return {
            "ready": False,
            "reason": "Workspace is not linked to a GitHub repository",
            "verification_status": meta.get("verification_status", "UNVERIFIED")
        }
        
    verification_status = meta.get("verification_status", "UNVERIFIED")
    token = github_service.get_token()
    
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
    if verification_status != "FIX VERIFIED":
        reason = f"Verification is {verification_status}. Only 'FIX VERIFIED' patches can be published."
    elif diverged:
        reason = f"Target branch '{meta['target_branch']}' has diverged on remote."
        
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
        "reason": reason
    }

@app.post("/api/github/publish")
async def github_publish(request: GitHubPublishRequest):
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
        
    token = github_service.get_token(request.token)
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
        
    title = request.title or meta.get("issue_description") or "Autonomous patch repair"
    if len(title) > 80:
        title = title[:77] + "..."
        
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
            problem_summary=meta.get("issue_description", "Autonomously repaired bug"),
            diagnosis_data=meta.get("diagnosis", meta.get("diagnosis_context", {})),
            verification_details=meta.get("verification_details"),
            model_name=nebius_client.model_name,
            is_mock_mode=nebius_client.mock_mode,
            custom_notes=request.custom_notes
        )
        workspace_manager.update_workspace_metadata(request.workspace_id, {"published_pr": pr_result})
        return pr_result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

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



