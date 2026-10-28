import pytest
import os
import shutil
import tempfile
from backend.app.workspace import WorkspaceManager

@pytest.fixture
def workspace_manager():
    wm = WorkspaceManager()
    yield wm
    for ws_id in list(wm.workspaces.keys()):
        wm.cleanup_workspace(ws_id)

def test_create_and_cleanup_workspace(workspace_manager):
    with tempfile.TemporaryDirectory() as temp_repo:
        os.system(f"cd {temp_repo} && git init && git config user.email 'test@test.com' && git config user.name 'Test' && echo 'test' > test.txt && git add test.txt && git commit -m 'Initial'")
        
        ws_id = workspace_manager.create_workspace(f"file://{temp_repo}")
        assert ws_id is not None
        
        ws_path = workspace_manager.get_workspace_path(ws_id)
        assert os.path.exists(os.path.join(ws_path, 'test.txt'))
        
        workspace_manager.cleanup_workspace(ws_id)
        assert not os.path.exists(ws_path)

def test_run_tests_allowed_command(workspace_manager):
    with tempfile.TemporaryDirectory() as temp_repo:
        os.system(f"cd {temp_repo} && git init && git config user.email 'test@test.com' && git config user.name 'Test' && echo 'def test_pass():\n    assert True' > test_file.py && git add test_file.py && git commit -m 'Initial'")
        ws_id = workspace_manager.create_workspace(f"file://{temp_repo}")
        
        result = workspace_manager.run_tests(ws_id, "pytest test_file.py")
        assert result["success"] is True
        assert "passed" in result["stdout"]

def test_run_tests_disallowed_command(workspace_manager):
     with tempfile.TemporaryDirectory() as temp_repo:
        os.system(f"cd {temp_repo} && git init && git config user.email 'test@test.com' && git config user.name 'Test' && echo 'test' > test.txt && git add test.txt && git commit -m 'Initial'")
        ws_id = workspace_manager.create_workspace(f"file://{temp_repo}")
        
        result = workspace_manager.run_tests(ws_id, "cat test.txt")
        assert result["success"] is False
        assert "not allowed" in result["stderr"]

def test_run_tests_shell_injection(workspace_manager):
    with tempfile.TemporaryDirectory() as temp_repo:
        os.system(f"cd {temp_repo} && git init && git config user.email 'test@test.com' && git config user.name 'Test' && echo 'test' > test.txt && git add test.txt && git commit -m 'Initial'")
        ws_id = workspace_manager.create_workspace(f"file://{temp_repo}")
        
        result = workspace_manager.run_tests(ws_id, "pytest test.py; rm -rf /")
        assert result["success"] is False
        assert "unsafe characters" in result["stderr"]
