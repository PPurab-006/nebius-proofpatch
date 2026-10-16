from fastapi import FastAPI, APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
import os
import shutil
import tempfile
from typing import Optional, List
from .workspace import WorkspaceManager
from .patch_engine import PatchEngine
from .nebius_client import NebiusClient

app = FastAPI(title="ProofPatch API", version="0.1.0")

workspace_manager = WorkspaceManager()
nebius_client = NebiusClient()

class RepositoryInput(BaseModel):
    url: str

class DiagnosisRequest(BaseModel):
    repo_url: str
    issue_description: str
    test_command: Optional[str] = None

class RepairRequest(BaseModel):
    repo_url: str
    issue_description: str
    diagnosis_context: dict
    test_command: Optional[str] = None

@app.get("/api/health")
async def health_check():
    return {
        "status": "ok", 
        "message": "ProofPatch Backend is running",
        "nebius_configured": not nebius_client.mock_mode,
        "model": nebius_client.model_name
    }

@app.post("/api/diagnose")
async def diagnose(request: DiagnosisRequest):
    # 1. Create isolated workspace
    try:
        ws_id = workspace_manager.create_workspace(request.repo_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    try:
        # 2. Run initial reproduction if test command provided
        repro_result = None
        if request.test_command:
            repro_result = workspace_manager.run_tests(ws_id, request.test_command)

        # 3. Gather code context (simplified: read all python files for MVP, or specific ones)
        ws_path = workspace_manager.get_workspace_path(ws_id)
        code_context = ""
        for root, _, files in os.walk(ws_path):
            if '.git' in root: continue
            for file in files:
                if file.endswith('.py'):
                    with open(os.path.join(root, file), 'r', errors='ignore') as f:
                        code_context += f"--- {file} ---\n{f.read()}\n\n"
        
        # Limit context to avoid token overflow
        code_context = code_context[:10000]

        # 4. Call model for diagnosis
        diagnosis = nebius_client.diagnose(request.issue_description, code_context)
        
        return {
            "status": "success",
            "workspace_id": ws_id,
            "reproduction": repro_result,
            "diagnosis": diagnosis
        }
    finally:
        # Cleanup (in a real app, might keep it alive for the repair step via ws_id)
        # For simplicity in this endpoint we clean up, or we could pass ws_id to repair
        workspace_manager.cleanup_workspace(ws_id)

@app.post("/api/repair")
async def propose_repair(request: RepairRequest):
    try:
        ws_id = workspace_manager.create_workspace(request.repo_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        # 1. Gather context
        ws_path = workspace_manager.get_workspace_path(ws_id)
        code_context = ""
        for root, _, files in os.walk(ws_path):
            if '.git' in root: continue
            for file in files:
                if file.endswith('.py'):
                    with open(os.path.join(root, file), 'r', errors='ignore') as f:
                        code_context += f"--- {file} ---\n{f.read()}\n\n"
        code_context = code_context[:10000]

        # 2. Generate patch
        patch = nebius_client.generate_patch(request.diagnosis_context, code_context)
        
        if not patch:
            return {"status": "error", "message": "Failed to generate patch"}

        # 3. Apply patch safely
        applied = PatchEngine.apply_patch(ws_path, patch)
        if not applied:
            return {
                "status": "error", 
                "message": "Failed to apply patch safely",
                "patch": patch
            }

        # 4. Verify
        verification_result = "UNVERIFIED"
        test_details = None
        if request.test_command:
            test_details = workspace_manager.run_tests(ws_id, request.test_command)
            if test_details["success"]:
                verification_result = "FIX VERIFIED"
            else:
                verification_result = "FIX FAILED"

        return {
            "status": "success",
            "patch": patch,
            "verification_status": verification_result,
            "verification_details": test_details
        }
    finally:
        workspace_manager.cleanup_workspace(ws_id)

