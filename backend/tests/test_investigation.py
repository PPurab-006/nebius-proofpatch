import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from backend.app.main import app, workspace_manager, nebius_client
from backend.app.intent_classifier import classify_intent, RequestIntent

client = TestClient(app)

def test_intent_classification_cases():
    # Targeted
    assert classify_intent("Fix this failing test in test_math.py").intent == RequestIntent.TARGETED
    assert classify_intent("Correct the incorrect subtraction implementation").intent == RequestIntent.TARGETED
    assert classify_intent("Fix the exception shown in this stack trace: KeyError: 'id'").intent == RequestIntent.TARGETED

    # Bug discovery
    assert classify_intent("Find bugs in this repository").intent == RequestIntent.BUG_DISCOVERY
    assert classify_intent("Audit the project for correctness problems").intent == RequestIntent.BUG_DISCOVERY
    assert classify_intent("Identify the most serious issues in this codebase").intent == RequestIntent.BUG_DISCOVERY

    # Improvement
    assert classify_intent("gimme some ways to improve it").intent == RequestIntent.IMPROVEMENT
    assert classify_intent("Improve maintainability and error handling").intent == RequestIntent.IMPROVEMENT
    assert classify_intent("Identify performance bottlenecks").intent == RequestIntent.IMPROVEMENT
    assert classify_intent("Review this project and recommend the highest-impact improvements").intent == RequestIntent.IMPROVEMENT

def test_api_inspect_benchmark_workspace():
    res = client.post("/api/inspect", json={"benchmark": "simple_bug"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert "workspace_id" in data
    assert "profile" in data
    assert "Python" in data["profile"]["languages"]
    assert "pytest" == data["profile"]["detected_test_command"]

def test_api_diagnose_broad_improvement_request():
    # Using mock mode or mock client for zero token consumption
    with patch.object(nebius_client, "investigate") as mock_inv:
        mock_inv.return_value = {
            "summary": "Repository code review identified 2 architectural improvements.",
            "findings": [
                {
                    "id": "finding-1",
                    "title": "Decouple parser from input loop",
                    "category": "performance",
                    "severity": "high",
                    "confidence": "high",
                    "impact": "Eliminates input lag",
                    "risk": "Low",
                    "files": ["extension.js"],
                    "evidence": "editor.on('input', parseAll)",
                    "explanation": "Synchronous parsing blocks the event loop.",
                    "action": "repair",
                    "proposed_fix": "Add debounce function to editor input listener."
                }
            ]
        }

        res = client.post(
            "/api/diagnose",
            json={
                "benchmark": "simple_bug",
                "issue_description": "gimme some ways to improve it"
            }
        )

        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["mode"] == "improvement"
        assert len(data["findings"]) == 1
        assert data["findings"][0]["title"] == "Decouple parser from input loop"
        assert "investigation" in data
        assert "diagnosis" in data

def test_api_diagnose_open_ended_bug_discovery():
    with patch.object(nebius_client, "investigate") as mock_inv:
        mock_inv.return_value = {
            "summary": "Audited codebase for latent correctness defects.",
            "findings": [
                {
                    "id": "finding-1",
                    "title": "Unhandled NoneType in boundary check",
                    "category": "defect",
                    "severity": "high",
                    "confidence": "high",
                    "impact": "Prevents crash on empty input",
                    "risk": "Low",
                    "files": ["math_utils.py"],
                    "evidence": "def subtract(a, b): return a + b",
                    "explanation": "Logic error adds instead of subtracting.",
                    "action": "repair",
                    "proposed_fix": "Change + to -"
                }
            ]
        }

        res = client.post(
            "/api/diagnose",
            json={
                "benchmark": "simple_bug",
                "issue_description": "Find bugs in this repository"
            }
        )

        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["mode"] == "bug_discovery"
        assert len(data["findings"]) == 1

def test_api_repair_with_selected_finding():
    # First create workspace and diagnose
    diag_res = client.post(
        "/api/diagnose",
        json={
            "benchmark": "simple_bug",
            "issue_description": "gimme some ways to improve it"
        }
    )
    ws_id = diag_res.json()["workspace_id"]

    selected_finding = {
        "id": "finding-1",
        "title": "Fix addition bug in subtract",
        "category": "defect",
        "severity": "high",
        "confidence": "high",
        "files": ["math_utils.py"],
        "evidence": "return a + b",
        "explanation": "Should subtract",
        "action": "repair",
        "proposed_fix": "Change + to -"
    }

    # Propose repair with selected_finding
    with patch.object(nebius_client, "generate_patch") as mock_patch:
        mock_patch.return_value = (
            "--- a/math_utils.py\n"
            "+++ b/math_utils.py\n"
            "@@ -4,3 +4,3 @@\n"
            " def subtract(a: int, b: int) -> int:\n"
            "     # Bug: Intentional addition instead of subtraction\n"
            "-    return a + b\n"
            "+    return a - b\n"
        )

        repair_res = client.post(
            "/api/repair",
            json={
                "workspace_id": ws_id,
                "issue_description": "gimme some ways to improve it",
                "selected_finding": selected_finding,
                "test_command": "pytest test_math_utils.py"
            }
        )

        assert repair_res.status_code == 200
        data = repair_res.json()
        assert data["status"] == "success"
        assert data["patch_applied"] is True
        assert data["verification_status"] == "FIX VERIFIED"

def test_benchmark_simple_bug_targeted_lifecycle():
    # targeted repair benchmark
    res = client.post(
        "/api/diagnose",
        json={
            "benchmark": "simple_bug",
            "issue_description": "test_subtract in math_utils.py fails because it adds instead of subtracting",
            "test_command": "pytest test_math_utils.py"
        }
    )
    assert res.status_code == 200
    diag = res.json()
    assert diag["mode"] == "targeted"
    ws_id = diag["workspace_id"]

    with patch.object(nebius_client, "generate_patch") as mock_patch:
        mock_patch.return_value = (
            "--- a/math_utils.py\n"
            "+++ b/math_utils.py\n"
            "@@ -4,3 +4,3 @@\n"
            " def subtract(a: int, b: int) -> int:\n"
            "     # Bug: Intentional addition instead of subtraction\n"
            "-    return a + b\n"
            "+    return a - b\n"
        )

        repair_res = client.post(
            "/api/repair",
            json={
                "workspace_id": ws_id,
                "issue_description": "test_subtract in math_utils.py fails",
                "diagnosis_context": diag["diagnosis"],
                "test_command": "pytest test_math_utils.py"
            }
        )

        assert repair_res.status_code == 200
        rep = repair_res.json()
        assert rep["patch_applied"] is True
        assert rep["verification_status"] == "FIX VERIFIED"

def test_benchmark_edge_case_targeted_lifecycle():
    res = client.post(
        "/api/diagnose",
        json={
            "benchmark": "edge_case",
            "issue_description": "truncate in text_utils.py has off-by-one boundary check",
            "test_command": "pytest test_text_utils.py"
        }
    )
    assert res.status_code == 200
    diag = res.json()
    ws_id = diag["workspace_id"]

    with patch.object(nebius_client, "generate_patch") as mock_patch:
        mock_patch.return_value = (
            "--- a/text_utils.py\n"
            "+++ b/text_utils.py\n"
            "@@ -1,5 +1,5 @@\n"
            " def truncate(text: str, max_length: int) -> str:\n"
            "     # Bug: Off-by-one boundary check causing unintended truncation\n"
            "-    if len(text) < max_length:\n"
            "+    if len(text) <= max_length:\n"
            "         return text\n"
            "     return text[:max_length] + \"...\"\n"
        )

        repair_res = client.post(
            "/api/repair",
            json={
                "workspace_id": ws_id,
                "issue_description": "truncate off-by-one boundary check",
                "diagnosis_context": diag["diagnosis"],
                "test_command": "pytest test_text_utils.py"
            }
        )

        assert repair_res.status_code == 200
        rep = repair_res.json()
        assert rep["patch_applied"] is True
        assert rep["verification_status"] == "FIX VERIFIED"
