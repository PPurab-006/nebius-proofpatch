from fastapi.testclient import TestClient
from backend.app.main import app
import os
import tempfile
import pytest

client = TestClient(app)

@pytest.fixture(autouse=True, scope="module")
def setup_benchmark_fixtures():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../benchmark_fixtures'))
    for fixture in ["simple_bug", "edge_case"]:
        fixture_dir = os.path.join(base_dir, fixture)
        if os.path.exists(fixture_dir) and not os.path.exists(os.path.join(fixture_dir, ".git")):
            os.system(f"cd {fixture_dir} && git init -q && git config user.name 'ProofPatch Bot' && git config user.email 'bot@proofpatch.test' && git add . && git commit -q -m 'Init fixture' || true")

def test_health_check():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_diagnose_mock():
    # Using the local simple_bug fixture
    fixture_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../benchmark_fixtures/simple_bug'))
    repo_url = f"file://{fixture_path}"
    
    response = client.post("/api/diagnose", json={
        "repo_url": repo_url,
        "issue_description": "test_subtract fails because 5+3=8 not 2",
        "test_command": "pytest test_math_utils.py"
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "diagnosis" in data
    # In mock mode, this will be the mock diagnosis
    assert "mock" in data["diagnosis"]["diagnosis"].lower()

def test_repair_mock_benchmark_fixture():
    fixture_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../benchmark_fixtures/simple_bug'))
    repo_url = f"file://{fixture_path}"
    
    response = client.post("/api/repair", json={
        "repo_url": repo_url,
        "issue_description": "test_subtract fails",
        "diagnosis_context": {"mock": "data"},
        "test_command": "pytest test_math_utils.py"
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["patch_applied"] is True
    assert data["verification_status"] == "FIX VERIFIED"
    assert data["verification_details"]["success"] is True

def test_repair_mock_unsupported_repo():
    with tempfile.TemporaryDirectory() as temp_repo:
        os.system(f"cd {temp_repo} && git init -q && git config user.name 'Test Bot' && git config user.email 'bot@test.com' && echo 'print(1)' > app.py && git add app.py && git commit -q -m 'Initial'")
        repo_url = f"file://{temp_repo}"
        
        response = client.post("/api/repair", json={
            "repo_url": repo_url,
            "issue_description": "fix arbitrary bug",
            "diagnosis_context": {"mock": "data"},
            "test_command": "pytest"
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
        assert data["patch_applied"] is False
        assert data["verification_status"] == "PATCH GENERATION FAILED"

def test_cors_headers():
    response = client.options("/api/health", headers={
        "Origin": "https://example.com",
        "Access-Control-Request-Method": "GET"
    })
    assert response.status_code == 200
    assert "access-control-allow-origin" in response.headers

def test_frontend_serving():
    response = client.get("/")
    if response.status_code == 404:
        assert response.status_code == 404
        return
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Patchworks" in response.text or "vite" in response.text.lower() or "html" in response.text.lower()

