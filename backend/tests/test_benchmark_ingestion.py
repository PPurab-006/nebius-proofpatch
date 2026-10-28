import os
import tempfile
import pytest
from fastapi.testclient import TestClient
from git import Repo

from backend.app.main import app
from backend.app.workspace import (
    WorkspaceManager,
    get_benchmark_fixtures_dir,
    resolve_benchmark_fixture_name,
    is_safe_url
)

client = TestClient(app)

@pytest.fixture
def workspace_manager():
    wm = WorkspaceManager()
    yield wm
    for ws_id in list(wm.workspaces.keys()):
        wm.cleanup_workspace(ws_id)

def test_resolve_benchmark_fixtures_dir():
    fixtures_dir = get_benchmark_fixtures_dir()
    assert os.path.isdir(fixtures_dir)
    assert os.path.exists(os.path.join(fixtures_dir, "edge_case"))
    assert os.path.exists(os.path.join(fixtures_dir, "simple_bug"))

def test_resolve_benchmark_fixture_name_variations():
    # Various valid benchmark target representations
    assert resolve_benchmark_fixture_name("edge_case") == "edge_case"
    assert resolve_benchmark_fixture_name("simple_bug") == "simple_bug"
    assert resolve_benchmark_fixture_name("benchmark://edge_case") == "edge_case"
    assert resolve_benchmark_fixture_name("benchmark://simple_bug") == "simple_bug"
    assert resolve_benchmark_fixture_name("benchmark:edge_case") == "edge_case"
    assert resolve_benchmark_fixture_name("benchmark:simple_bug") == "simple_bug"

    # Container-path legacy format (from the observed error in the prompt)
    assert resolve_benchmark_fixture_name("file:///app/benchmark_fixtures/edge_case") == "edge_case"
    assert resolve_benchmark_fixture_name("file:///app/benchmark_fixtures/simple_bug") == "simple_bug"
    assert resolve_benchmark_fixture_name("/app/benchmark_fixtures/edge_case") == "edge_case"

    # Real remote repositories should NOT be resolved as benchmark fixtures
    assert resolve_benchmark_fixture_name("https://github.com/org/repo.git") is None
    assert resolve_benchmark_fixture_name("http://example.com/repo") is None
    assert resolve_benchmark_fixture_name("") is None
    assert resolve_benchmark_fixture_name(None) is None

def test_resolve_benchmark_security_traversal_rejection():
    # Path traversal attempts must return None
    assert resolve_benchmark_fixture_name("../../etc/passwd") is None
    assert resolve_benchmark_fixture_name("benchmark://../../etc") is None
    assert resolve_benchmark_fixture_name("file:///app/benchmark_fixtures/../../etc") is None
    assert resolve_benchmark_fixture_name("edge_case/../../secret") is None
    assert resolve_benchmark_fixture_name("non_existent_fixture_xyz") is None

def test_create_workspace_from_benchmark_edge_case(workspace_manager):
    ws_id = workspace_manager.create_workspace_from_benchmark("edge_case")
    assert ws_id is not None
    ws_path = workspace_manager.get_workspace_path(ws_id)

    # Fixture files must exist
    assert os.path.exists(os.path.join(ws_path, "text_utils.py"))
    assert os.path.exists(os.path.join(ws_path, "test_text_utils.py"))

    # Must be a newly initialized Git repository with clean commit
    repo = Repo(ws_path)
    assert repo.head.is_valid()
    commit = repo.head.commit
    assert "edge_case" in commit.message

    metadata = workspace_manager.get_workspace_metadata(ws_id)
    assert metadata["source_type"] == "benchmark"
    assert metadata["benchmark_name"] == "edge_case"
    assert metadata["starting_commit_sha"] == commit.hexsha

    # Test execution reproduces the bug
    test_result = workspace_manager.run_tests(ws_id, "pytest test_text_utils.py")
    assert test_result["returncode"] == 1
    assert "FAILED" in test_result["stdout"] or "failed" in test_result["stdout"]

def test_create_workspace_from_benchmark_simple_bug(workspace_manager):
    ws_id = workspace_manager.create_workspace_from_benchmark("simple_bug")
    assert ws_id is not None
    ws_path = workspace_manager.get_workspace_path(ws_id)

    assert os.path.exists(os.path.join(ws_path, "math_utils.py"))
    assert os.path.exists(os.path.join(ws_path, "test_math_utils.py"))

    metadata = workspace_manager.get_workspace_metadata(ws_id)
    assert metadata["source_type"] == "benchmark"
    assert metadata["benchmark_name"] == "simple_bug"

    test_result = workspace_manager.run_tests(ws_id, "pytest test_math_utils.py")
    assert test_result["returncode"] == 1
    assert "FAILED" in test_result["stdout"] or "failed" in test_result["stdout"]

def test_create_workspace_rejects_invalid_benchmark_fixture(workspace_manager):
    with pytest.raises(ValueError, match="Invalid benchmark fixture identifier|traversal detected|not found"):
        workspace_manager.create_workspace_from_benchmark("../../etc")

    with pytest.raises(ValueError, match="Invalid benchmark fixture identifier|traversal detected|not found"):
        workspace_manager.create_workspace_from_benchmark("invalid_fixture_123")

def test_normal_repository_ingestion_preserved(workspace_manager):
    # Verify genuine Git repositories still clone and operate normally
    with tempfile.TemporaryDirectory() as remote_repo_dir:
        repo = Repo.init(remote_repo_dir)
        with repo.config_writer() as cw:
            cw.set_value("user", "name", "Git Ingestion Test")
            cw.set_value("user", "email", "test@ingestion.com")

        test_file = os.path.join(remote_repo_dir, "app.py")
        with open(test_file, "w") as f:
            f.write("def add(a, b):\n    return a + b\n")
        repo.git.add(A=True)
        repo.index.commit("Initial remote commit")

        # Ingest through normal create_workspace
        ws_id = workspace_manager.create_workspace(f"file://{remote_repo_dir}")
        assert ws_id is not None
        ws_path = workspace_manager.get_workspace_path(ws_id)
        assert os.path.exists(os.path.join(ws_path, "app.py"))

        metadata = workspace_manager.get_workspace_metadata(ws_id)
        assert metadata["source_type"] == "git"
        assert metadata["repo_url"] == f"file://{remote_repo_dir}"

def test_security_url_validation_blocks_arbitrary_local_paths():
    # Blocks arbitrary system file paths
    assert is_safe_url("file:///etc/passwd") is False
    assert is_safe_url("file:///etc/shadow") is False
    assert is_safe_url("file:///tmp/../../etc/passwd") is False
    assert is_safe_url("file:///home/user/.ssh/id_rsa") is False

    # Allows benchmark fixture scheme
    assert is_safe_url("benchmark://edge_case") is True
    assert is_safe_url("benchmark://simple_bug") is True
    assert is_safe_url("benchmark://../../etc") is False

    # Preserves SSRF blocklist
    assert is_safe_url("http://127.0.0.1/evil") is False
    assert is_safe_url("http://169.254.169.254/latest/meta-data") is False

def test_api_benchmark_endpoints():
    # List benchmarks
    list_res = client.get("/api/benchmarks")
    assert list_res.status_code == 200
    benchmarks = list_res.json()["benchmarks"]
    assert "edge_case" in benchmarks
    assert "simple_bug" in benchmarks

    # Create workspace endpoint for edge_case
    res_edge = client.post("/api/benchmark/workspace", json={"fixture": "edge_case"})
    assert res_edge.status_code == 200
    edge_data = res_edge.json()
    assert edge_data["status"] == "success"
    assert edge_data["fixture"] == "edge_case"
    assert "workspace_id" in edge_data
    assert edge_data["metadata"]["source_type"] == "benchmark"

    # Clean up workspace
    client.delete(f"/api/workspace/{edge_data['workspace_id']}")

    # Reject traversal / invalid fixture in API
    bad_res = client.post("/api/benchmark/workspace", json={"fixture": "../../etc"})
    assert bad_res.status_code == 400

    bad_res2 = client.post("/api/benchmark/workspace", json={"fixture": "unknown_fixture"})
    assert bad_res2.status_code == 400

def test_api_diagnose_and_repair_with_edge_case_benchmark():
    # Test diagnosing using the benchmark parameter
    diag_res = client.post("/api/diagnose", json={
        "benchmark": "edge_case",
        "issue_description": "truncate boundary off-by-one bug",
        "test_command": "pytest test_text_utils.py"
    })
    assert diag_res.status_code == 200
    diag_data = diag_res.json()
    assert diag_data["status"] == "success"
    ws_id = diag_data["workspace_id"]

    # Test repair using the resulting workspace_id
    repair_res = client.post("/api/repair", json={
        "workspace_id": ws_id,
        "issue_description": "truncate boundary off-by-one bug",
        "diagnosis_context": diag_data["diagnosis"],
        "test_command": "pytest test_text_utils.py"
    })
    assert repair_res.status_code == 200
    repair_data = repair_res.json()
    assert repair_data["status"] == "success"
    assert repair_data["patch_applied"] is True
    assert repair_data["verification_status"] == "FIX VERIFIED"

    client.delete(f"/api/workspace/{ws_id}")

def test_api_diagnose_with_legacy_container_url():
    # Observed error in prompt: user clicks Load edge_case which produced file:///app/benchmark_fixtures/edge_case
    diag_res = client.post("/api/diagnose", json={
        "repo_url": "file:///app/benchmark_fixtures/edge_case",
        "issue_description": "truncate off-by-one bug",
        "test_command": "pytest test_text_utils.py"
    })
    assert diag_res.status_code == 200
    diag_data = diag_res.json()
    assert diag_data["status"] == "success"
    ws_id = diag_data["workspace_id"]
    assert ws_id is not None
    client.delete(f"/api/workspace/{ws_id}")
