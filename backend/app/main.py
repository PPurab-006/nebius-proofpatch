from fastapi import FastAPI, APIRouter, HTTPException, BackgroundTasks, UploadFile, File, Form
from pydantic import BaseModel
import os
import shutil
import tempfile
from typing import Optional, List
import re
from .workspace import WorkspaceManager
from .patch_engine import PatchEngine
from .nebius_client import NebiusClient

app = FastAPI(title="ProofPatch API", version="0.1.0")

workspace_manager = WorkspaceManager()
nebius_client = NebiusClient()

class DiagnosisRequest(BaseModel):
    repo_url: Optional[str] = None
    workspace_id: Optional[str] = None
    issue_description: str
    test_command: Optional[str] = None

class RepairRequest(BaseModel):
    repo_url: Optional[str] = None
    workspace_id: Optional[str] = None
    issue_description: str
    diagnosis_context: dict
    test_command: Optional[str] = None

class RollbackRequest(BaseModel):
    workspace_id: str

def redact_secrets(text: str) -> str:
    # Basic secret redaction
    text = re.sub(r'(api_key|API_KEY|secret|SECRET|password|PASSWORD)\s*=\s*["\'][^"\']+["\']', r'\1 = "***REDACTED***"', text)
    text = re.sub(r'(Bearer\s+)[A-Za-z0-9\-\._~]+', r'\1***REDACTED***', text)
    text = re.sub(r'-----BEGIN[A-Z\s]+PRIVATE KEY-----.*?-----END[A-Z\s]+PRIVATE KEY-----', '***REDACTED_PRIVATE_KEY***', text, flags=re.DOTALL)
    return text

def build_context(ws_path: str) -> str:
    code_context = ""
    ignore_dirs = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', 'env'}
    for root, dirs, files in os.walk(ws_path):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        for file in files:
            # Filter binaries out roughly, keep common source files
            if file.endswith(('.py', '.js', '.ts', '.tsx', '.jsx', '.json', '.md', '.txt')):
                file_path = os.path.join(root, file)
                try:
                    # Skip files larger than 100KB to prevent memory issues
                    if os.path.getsize(file_path) > 100 * 1024:
                        code_context += f"--- {file} ---\n[File truncated: Too large]\n\n"
                        continue

                    with open(file_path, 'r', errors='ignore') as f:
                        content = f.read()

                        # Truncate large files
                        if len(content) > 10000:
                            content = content[:10000] + "\n\n... [File truncated: Exceeds 10,000 characters]"

                        code_context += f"--- {file} ---\n<untrusted_source_code>\n{redact_secrets(content)}\n</untrusted_source_code>\n\n"
                except Exception as e:
                    code_context += f"--- {file} ---\n[Error reading file: {str(e)}]\n\n"

    # Cap total context size
    if len(code_context) > 50000:
        code_context = code_context[:50000] + "\n\n... [Context truncated: Exceeds total size limit]"

    return code_context

@app.get("/api/health")
async def health_check():
    return {
        "status": "ok", 
        "message": "ProofPatch Backend is running",
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

@app.post("/api/diagnose")
async def diagnose(request: DiagnosisRequest):
    ws_id = request.workspace_id
    is_new_workspace = False
    
    try:
        if not ws_id:
            if not request.repo_url:
                raise HTTPException(status_code=400, detail="Either workspace_id or repo_url must be provided")
            ws_id = workspace_manager.create_workspace(request.repo_url)
            is_new_workspace = True

        repro_result = None
        if request.test_command:
            repro_result = workspace_manager.run_tests(ws_id, request.test_command)

        ws_path = workspace_manager.get_workspace_path(ws_id)
        code_context = build_context(ws_path)

        diagnosis = nebius_client.diagnose(request.issue_description, code_context)
        
        return {
            "status": "success",
            "workspace_id": ws_id,
            "reproduction": repro_result,
            "diagnosis": diagnosis
        }
    except Exception as e:
        if is_new_workspace and ws_id:
            workspace_manager.cleanup_workspace(ws_id)
        raise HTTPException(status_code=400, detail=str(e))
    # We do NOT cleanup workspace here because the user might apply a patch to it next.
    # A background cleanup job or timeout would be ideal in prod.

@app.post("/api/repair")
async def propose_repair(request: RepairRequest):
    ws_id = request.workspace_id
    is_new_workspace = False

    try:
        if not ws_id:
            if not request.repo_url:
                raise HTTPException(status_code=400, detail="Either workspace_id or repo_url must be provided")
            ws_id = workspace_manager.create_workspace(request.repo_url)
            is_new_workspace = True

        ws_path = workspace_manager.get_workspace_path(ws_id)
        code_context = build_context(ws_path)

        patch = nebius_client.generate_patch(request.diagnosis_context, code_context)
        
        if not patch:
            return {"status": "error", "message": "Failed to generate patch"}

        applied = PatchEngine.apply_patch(ws_path, patch)
        if not applied:
            return {
                "status": "error", 
                "message": "Failed to apply patch safely or unidiff validation failed",
                "patch": patch,
                "verification_status": "APPLY FAILED"
            }

        verification_result = "UNVERIFIED"
        test_details = None
        if request.test_command:
            test_details = workspace_manager.run_tests(ws_id, request.test_command)
            if test_details["success"]:
                verification_result = "FIX VERIFIED"
            elif test_details["returncode"] != -1 and test_details["stdout"]:
                 verification_result = "FIX PARTIALLY VERIFIED"
            else:
                verification_result = "FIX FAILED"

        return {
            "status": "success",
            "workspace_id": ws_id,
            "patch": patch,
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

