import os
import shutil
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from git import Repo

from backend.app.main import app, workspace_manager, github_service, nebius_client
from backend.app.github_service import GitHubService, sanitize_branch_name, REPO_NAME_REGEX, BRANCH_NAME_REGEX

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_github_service():
    """Ensure github_service token is cleared between tests."""
    github_service.set_session_token(None)
    github_service.default_token = ""
    yield
    github_service.set_session_token(None)
    github_service.default_token = ""

def test_sanitize_branch_name():
    assert sanitize_branch_name("main") == "main"
    assert sanitize_branch_name("feature/fix-1") == "feature/fix-1"
    assert sanitize_branch_name("../../evil") == "evil"
    assert sanitize_branch_name("-flag") == "flag"
    assert sanitize_branch_name("---") == "patchworks-fix"
    assert sanitize_branch_name("") == "patchworks-fix"

def test_repo_and_branch_regex():
    assert REPO_NAME_REGEX.match("valid-repo_1.0")
    assert not REPO_NAME_REGEX.match("invalid/repo")
    assert not REPO_NAME_REGEX.match("repo; rm -rf /")
    assert BRANCH_NAME_REGEX.match("feature/branch-1")
    assert not BRANCH_NAME_REGEX.match("branch;ls")

def test_github_status_disconnected():
    res = client.get("/api/github/status")
    assert res.status_code == 200
    data = res.json()
    assert data["connected"] is False
    assert data["user"] is None
    assert data["auth_type"] == "none"

def test_github_connect_and_disconnect():
    fake_token = "ghp_fakeTokenSecret12345"
    
    # Mock verify_token returning valid user
    with patch.object(github_service, "verify_token", return_value={
        "valid": True,
        "login": "octocat",
        "name": "Mona Lisa Octocat",
        "avatar_url": "https://avatars.githubusercontent.com/u/583231",
        "html_url": "https://github.com/octocat",
        "scopes": ["repo"]
    }):
        # Connect
        res = client.post("/api/github/connect", json={"token": fake_token})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "connected"
        assert data["user"]["login"] == "octocat"
        # Token must never be present in the response
        assert fake_token not in res.text

        # Verify status endpoint reflects connection
        status_res = client.get("/api/github/status")
        assert status_res.status_code == 200
        assert status_res.json()["connected"] is True
        assert status_res.json()["user"]["login"] == "octocat"
        assert fake_token not in status_res.text

        # Disconnect
        disc_res = client.post("/api/github/disconnect")
        assert disc_res.status_code == 200
        assert disc_res.json()["status"] == "disconnected"

        # Verify status is disconnected again
        status_after = client.get("/api/github/status")
        assert status_after.json()["connected"] is False

def test_github_connect_invalid_token():
    with patch.object(github_service, "verify_token", return_value={
        "valid": False,
        "error": "Invalid or expired GitHub credentials"
    }):
        res = client.post("/api/github/connect", json={"token": "invalid_token"})
        assert res.status_code == 400
        assert "Invalid or expired GitHub credentials" in res.json()["detail"]

def test_github_endpoints_require_auth():
    # When disconnected, repos and branches must return 401
    res1 = client.get("/api/github/repos")
    assert res1.status_code == 401

    res2 = client.get("/api/github/repos/owner/repo/branches")
    assert res2.status_code == 401

def test_github_branches_invalid_names():
    github_service.set_session_token("valid_token")
    # Path traversal / invalid characters must be rejected
    res = client.get("/api/github/repos/owner../repo/branches")
    assert res.status_code == 400
    assert "Invalid owner or repository name" in res.json()["detail"]

def test_github_workspace_validation_and_registration():
    github_service.set_session_token("valid_token")

    # Invalid repo name rejected
    res_bad = client.post("/api/github/workspace", json={
        "owner": "bad/owner",
        "repo": "bad;repo",
        "branch": "main"
    })
    assert res_bad.status_code == 400

    # Mock clone_github_repo
    with patch.object(github_service, "clone_github_repo", return_value="abcdef1234567890abcdef1234567890abcdef12"):
        res = client.post("/api/github/workspace", json={
            "owner": "testowner",
            "repo": "testrepo",
            "branch": "main"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["starting_commit_sha"] == "abcdef1234567890abcdef1234567890abcdef12"
        ws_id = data["workspace_id"]

        # Check metadata stored in workspace_manager
        meta = workspace_manager.get_workspace_metadata(ws_id)
        assert meta["source_type"] == "github"
        assert meta["owner"] == "testowner"
        assert meta["repo"] == "testrepo"
        assert meta["target_branch"] == "main"
        assert meta["starting_commit_sha"] == "abcdef1234567890abcdef1234567890abcdef12"

        # Cleanup
        workspace_manager.cleanup_workspace(ws_id)

def test_publication_gate_blocks_unverified():
    """Verify that only FIX VERIFIED status can be published."""
    github_service.set_session_token("valid_token")

    # Create dummy git workspace
    temp_dir = tempfile.mkdtemp(prefix="gate_test_")
    repo = Repo.init(temp_dir)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test")
        cw.set_value("user", "email", "test@test.com")
    test_file = os.path.join(temp_dir, "test.txt")
    with open(test_file, "w") as f:
        f.write("initial\n")
    repo.git.add(A=True)
    repo.index.commit("Initial commit")
    head_sha = repo.head.commit.hexsha

    ws_id = "test_gate_ws_1"
    workspace_manager.register_workspace(
        workspace_id=ws_id,
        workspace_path=temp_dir,
        metadata={
            "source_type": "github",
            "owner": "testowner",
            "repo": "testrepo",
            "target_branch": "main",
            "starting_commit_sha": head_sha,
            "verification_status": "FIX FAILED" # NOT verified!
        }
    )

    try:
        # Check readiness endpoint
        readiness = client.get(f"/api/github/publish/readiness?workspace_id={ws_id}")
        assert readiness.status_code == 200
        assert readiness.json()["ready"] is False
        assert readiness.json()["verification_status"] == "FIX FAILED"

        # Attempt to publish -> must be rejected by backend gate with 400
        publish_res = client.post("/api/github/publish", json={
            "workspace_id": ws_id,
            "title": "Unverified fix attempt"
        })
        assert publish_res.status_code == 400
        assert "Publication gate blocked" in publish_res.json()["detail"]
        assert "FIX FAILED" in publish_res.json()["detail"]

        # Now test with VERIFICATION INCOMPLETE
        workspace_manager.update_workspace_metadata(ws_id, {"verification_status": "VERIFICATION INCOMPLETE"})
        publish_res2 = client.post("/api/github/publish", json={"workspace_id": ws_id})
        assert publish_res2.status_code == 400
        assert "VERIFICATION INCOMPLETE" in publish_res2.json()["detail"]

        # Now test with UNVERIFIED
        workspace_manager.update_workspace_metadata(ws_id, {"verification_status": "UNVERIFIED"})
        publish_res3 = client.post("/api/github/publish", json={"workspace_id": ws_id})
        assert publish_res3.status_code == 400
        assert "UNVERIFIED" in publish_res3.json()["detail"]

    finally:
        workspace_manager.cleanup_workspace(ws_id)
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

def test_publication_divergence_detection():
    """Verify that remote branch divergence halts publication."""
    github_service.set_session_token("valid_token")

    temp_dir = tempfile.mkdtemp(prefix="divergence_test_")
    repo = Repo.init(temp_dir)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test")
        cw.set_value("user", "email", "test@test.com")
    test_file = os.path.join(temp_dir, "test.txt")
    with open(test_file, "w") as f:
        f.write("initial\n")
    repo.git.add(A=True)
    repo.index.commit("Initial commit")
    head_sha = repo.head.commit.hexsha

    ws_id = "test_div_ws_1"
    workspace_manager.register_workspace(
        workspace_id=ws_id,
        workspace_path=temp_dir,
        metadata={
            "source_type": "github",
            "owner": "testowner",
            "repo": "testrepo",
            "target_branch": "main",
            "starting_commit_sha": head_sha,
            "verification_status": "FIX VERIFIED"
        }
    )

    try:
        # Mock remote divergence (current remote commit is different)
        with patch.object(github_service, "check_divergence", return_value=(True, "new_remote_sha_9999")):
            readiness = client.get(f"/api/github/publish/readiness?workspace_id={ws_id}")
            assert readiness.status_code == 200
            data = readiness.json()
            assert data["ready"] is False
            assert data["diverged"] is True

            # Attempt publish
            publish_res = client.post("/api/github/publish", json={"workspace_id": ws_id})
            assert publish_res.status_code == 409
            assert "diverged" in publish_res.json()["detail"].lower()
    finally:
        workspace_manager.cleanup_workspace(ws_id)
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

def test_successful_publication_flow():
    """Verify that FIX VERIFIED patch publishes to a branch and creates a PR."""
    github_service.set_session_token("valid_token")

    temp_dir = tempfile.mkdtemp(prefix="pub_success_test_")
    repo = Repo.init(temp_dir)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test")
        cw.set_value("user", "email", "test@test.com")
    test_file = os.path.join(temp_dir, "app.py")
    with open(test_file, "w") as f:
        f.write("def foo():\n    return 1\n")
    repo.git.add(A=True)
    repo.index.commit("Initial commit")
    head_sha = repo.head.commit.hexsha

    # Modify file to have staged change
    with open(test_file, "w") as f:
        f.write("def foo():\n    return 2\n")

    ws_id = "test_pub_success_ws"
    workspace_manager.register_workspace(
        workspace_id=ws_id,
        workspace_path=temp_dir,
        metadata={
            "source_type": "github",
            "owner": "octocat",
            "repo": "hello-world",
            "target_branch": "main",
            "starting_commit_sha": head_sha,
            "verification_status": "FIX VERIFIED",
            "issue_description": "Fix foo return value",
            "diagnosis": {
                "diagnosis": "Return value was 1 instead of 2.",
                "evidence": "Observed return 1 in app.py",
                "files_to_modify": ["app.py"],
                "proposed_fix_description": "Change return 1 to return 2",
                "regression_risks": "None identified"
            },
            "verification_details": {
                "success": True,
                "returncode": 0,
                "stdout": "pytest 1 passed in 0.05s"
            }
        }
    )

    try:
        # Mock git push subprocess and GitHub PR API POST call
        mock_publish_result = {
            "status": "success",
            "pr_url": "https://github.com/octocat/hello-world/pull/42",
            "pr_number": 42,
            "branch": "patchworks/fix-test_pub",
            "commit_sha": "1234567890abcdef1234567890abcdef12345678",
            "target_branch": "main"
        }

        with patch.object(github_service, "check_divergence", return_value=(False, head_sha)), \
             patch.object(github_service, "publish_pull_request", return_value=mock_publish_result):
            
            # Check readiness
            readiness = client.get(f"/api/github/publish/readiness?workspace_id={ws_id}")
            assert readiness.status_code == 200
            assert readiness.json()["ready"] is True
            assert readiness.json()["verification_status"] == "FIX VERIFIED"

            # Publish
            pub_res = client.post("/api/github/publish", json={
                "workspace_id": ws_id,
                "title": "fix: resolve return value in app.py",
                "custom_notes": "Reviewed and verified via automated test suite."
            })

            assert pub_res.status_code == 200
            res_data = pub_res.json()
            assert res_data["status"] == "success"
            assert res_data["pr_url"] == "https://github.com/octocat/hello-world/pull/42"
            assert res_data["pr_number"] == 42
            assert res_data["branch"] == "patchworks/fix-test_pub"

            # Check that workspace metadata was updated with publication result
            meta_after = workspace_manager.get_workspace_metadata(ws_id)
            assert meta_after["published_pr"]["pr_number"] == 42

    finally:
        workspace_manager.cleanup_workspace(ws_id)
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

def test_pr_body_builder_truthfulness():
    """Verify that PR body truthfully reports mock mode and test output."""
    body_mock = github_service._build_pr_body(
        title="Fix calculation",
        problem_summary="Calculated incorrect tax",
        diagnosis_data={
            "diagnosis": "Missing rounding",
            "evidence": "Rounding error in calc.py:10",
            "files_to_modify": ["calc.py"],
            "proposed_fix_description": "Add round()",
            "regression_risks": "Low"
        },
        verification_details={
            "returncode": 0,
            "stdout": "test_tax PASSED [100%]"
        },
        model_name="nvidia/llama-3.1-nemotron-70b-instruct",
        is_mock_mode=True,
        new_branch="patchworks/fix-abc",
        target_branch="main",
        commit_sha="abcdef1234567890",
        custom_notes="Automated run"
    )

    assert "Simulated Mock Mode" in body_mock
    assert "FIX VERIFIED" in body_mock
    assert "test_tax PASSED [100%]" in body_mock
    assert "patchworks/fix-abc" in body_mock

    # Live mode body
    body_live = github_service._build_pr_body(
        title="Fix calculation",
        problem_summary="Calculated incorrect tax",
        diagnosis_data={"diagnosis": "Missing rounding"},
        verification_details={"returncode": 0, "stdout": "test passed"},
        model_name="nvidia/llama-3.1-nemotron-70b-instruct",
        is_mock_mode=False,
        new_branch="patchworks/fix-live",
        target_branch="main",
        commit_sha="abcdef1234567890"
    )
    assert "Live Nebius AI Cloud" in body_live
    assert "nvidia/llama-3.1-nemotron-70b-instruct" in body_live

def test_github_oauth_flow():
    # 1. When not configured
    github_service.client_id = ""
    github_service.client_secret = ""
    res = client.get("/api/github/oauth/url")
    assert res.status_code == 400

    # 2. When configured
    github_service.client_id = "test_client_id"
    github_service.client_secret = "test_client_secret"
    res = client.get("/api/github/oauth/url?redirect_uri=https://example.com/callback")
    assert res.status_code == 200
    url = res.json()["url"]
    assert "github.com/login/oauth/authorize" in url
    assert "client_id=test_client_id" in url
    assert "state=" in url

    # Extract state from URL
    state = url.split("state=")[1].split("&")[0]
    assert github_service.validate_oauth_state(state) is True
    # Replay state should fail (one-time use)
    assert github_service.validate_oauth_state(state) is False

def test_github_oauth_callback():
    github_service.client_id = "test_client_id"
    github_service.client_secret = "test_client_secret"
    state = github_service.create_oauth_state()

    with patch.object(github_service, "exchange_oauth_code", return_value=(True, "gho_test_token_123", None)), \
         patch.object(github_service, "verify_token", return_value={"valid": True, "login": "testuser"}):
        res = client.get(f"/api/github/oauth/callback?code=fake_code&state={state}", follow_redirects=False)
        assert res.status_code == 303
        assert res.headers["location"] == "/?github_connected=true"
        assert github_service.active_session_token == "gho_test_token_123"

