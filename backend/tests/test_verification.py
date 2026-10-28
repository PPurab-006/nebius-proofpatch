import pytest
import os
import tempfile
from fastapi.testclient import TestClient
from backend.app.main import app, workspace_manager, nebius_client

client = TestClient(app)

def test_failed_test_yields_fix_failed_not_partial(monkeypatch):
    """
    Regression test for Bug 3.A:
    A failed test run producing stdout must be classified as FIX FAILED,
    never FIX PARTIALLY VERIFIED.
    """
    with tempfile.TemporaryDirectory() as temp_repo:
        os.system(
            f"cd {temp_repo} && git init -q && "
            f"git config user.name 'Bot' && git config user.email 'b@b.com' && "
            f"echo 'def test_fail(): assert 1 == 2' > test_fail.py && "
            f"echo 'def code(): return 1' > code.py && "
            f"git add . && git commit -q -m 'Initial'"
        )

        ws_id = workspace_manager.create_workspace(f"file://{temp_repo}")

        valid_patch = (
            "--- a/code.py\n"
            "+++ b/code.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-def code(): return 1\n"
            "+def code(): return 2\n"
        )
        monkeypatch.setattr(nebius_client, "generate_patch", lambda diag, ctx: valid_patch)

        response = client.post("/api/repair", json={
            "workspace_id": ws_id,
            "issue_description": "fix test",
            "diagnosis_context": {"mock": "data"},
            "test_command": "pytest test_fail.py"
        })

        assert response.status_code == 200
        data = response.json()
        assert data["verification_status"] == "FIX FAILED"
        assert data["patch_applied"] is True
        assert data["verification_details"]["success"] is False
        assert data["verification_details"]["returncode"] != 0
        assert "assert 1 == 2" in data["verification_details"]["stdout"]
        workspace_manager.cleanup_workspace(ws_id)

def test_disallowed_command_yields_verification_incomplete(monkeypatch):
    """
    When verification cannot run or command fails validation,
    status must be VERIFICATION INCOMPLETE.
    """
    with tempfile.TemporaryDirectory() as temp_repo:
        os.system(
            f"cd {temp_repo} && git init -q && "
            f"git config user.name 'Bot' && git config user.email 'b@b.com' && "
            f"echo 'x = 1' > file.py && git add . && git commit -q -m 'Init'"
        )

        ws_id = workspace_manager.create_workspace(f"file://{temp_repo}")

        valid_patch = (
            "--- a/file.py\n"
            "+++ b/file.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-x = 1\n"
            "+x = 2\n"
        )
        monkeypatch.setattr(nebius_client, "generate_patch", lambda diag, ctx: valid_patch)

        response = client.post("/api/repair", json={
            "workspace_id": ws_id,
            "issue_description": "fix bug",
            "diagnosis_context": {"mock": "data"},
            "test_command": "disallowed_command test.py"
        })

        assert response.status_code == 200
        data = response.json()
        assert data["verification_status"] == "VERIFICATION INCOMPLETE"
        assert data["patch_applied"] is True
        assert data["verification_details"]["returncode"] == -1
        workspace_manager.cleanup_workspace(ws_id)

def test_unverified_when_no_test_command(monkeypatch):
    """
    When patch is applied without a test command, status must be UNVERIFIED.
    """
    with tempfile.TemporaryDirectory() as temp_repo:
        os.system(
            f"cd {temp_repo} && git init -q && "
            f"git config user.name 'Bot' && git config user.email 'b@b.com' && "
            f"echo 'x = 1' > file.py && git add . && git commit -q -m 'Init'"
        )

        ws_id = workspace_manager.create_workspace(f"file://{temp_repo}")

        valid_patch = (
            "--- a/file.py\n"
            "+++ b/file.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-x = 1\n"
            "+x = 2\n"
        )
        monkeypatch.setattr(nebius_client, "generate_patch", lambda diag, ctx: valid_patch)

        response = client.post("/api/repair", json={
            "workspace_id": ws_id,
            "issue_description": "fix",
            "diagnosis_context": {"mock": "data"}
        })

        assert response.status_code == 200
        data = response.json()
        assert data["verification_status"] == "UNVERIFIED"
        assert data["patch_applied"] is True
        assert data["verification_details"] is None
        workspace_manager.cleanup_workspace(ws_id)
