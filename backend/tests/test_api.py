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

def test_repair_mock():
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
    
    # In mock mode, applying the mock patch will fail since 'mock.py' doesn't exist
    # So we expect 'error' and 'Failed to apply patch safely'
    assert data["status"] == "error"
    assert "Failed to apply patch" in data["message"]
    assert "mock" in data["patch"]
