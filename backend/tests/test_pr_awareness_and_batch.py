import os
import shutil
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from git import Repo

from backend.app.main import app, workspace_manager, github_service, nebius_client
from backend.app.reporting import compute_finding_fingerprint
from backend.app.auth import AuthUser

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_service_state():
    github_service.set_session_token(None)
    github_service.default_token = "ghp_test_fixture_token_12345"
    yield
    github_service.set_session_token(None)
    github_service.default_token = ""

def create_git_workspace_with_findings(findings, test_content="def test_ok(): assert True\n"):
    temp_dir = tempfile.mkdtemp()
    os.system(
        f"cd {temp_dir} && git init -q && "
        f"git config user.name 'Tester' && git config user.email 'test@patchworks.test' && "
        f"echo 'def add(a, b): return a + b' > app.py && "
        f"echo '{test_content}' > test_app.py && "
        f"git add . && git commit -q -m 'Initial commit'"
    )
    ws_id = workspace_manager.create_workspace(f"file://{temp_dir}")
    repo = Repo(workspace_manager.get_workspace_path(ws_id))
    head_sha = repo.head.commit.hexsha

    workspace_manager.update_workspace_metadata(ws_id, {
        "source_type": "github",
        "owner": "testorg",
        "repo": "testrepo",
        "target_branch": "main",
        "starting_commit_sha": head_sha,
        "findings": findings,
        "test_command": "pytest test_app.py"
    })
    return ws_id, temp_dir


def test_1_open_pr_detected_and_displayed():
    finding = {
        "id": "finding-1",
        "title": "Fix division by zero in calculate_rate",
        "category": "defect",
        "severity": "high",
        "confidence": "high",
        "files": ["app.py"],
        "line_numbers": [1],
        "explanation": "No check for zero denominator",
        "proposed_fix": "Add guard check"
    }
    ws_id, temp_dir = create_git_workspace_with_findings([finding])
    fp = compute_finding_fingerprint(finding)

    mock_pr = {
        "number": 101,
        "title": "fix: resolve division by zero in calculate_rate",
        "state": "open",
        "is_merged": False,
        "merged_at": None,
        "closed_at": None,
        "html_url": "https://github.com/testorg/testrepo/pull/101",
        "body": f"## Summary\nFixes issue\n\n<!-- patchworks-finding-fingerprint: {fp} -->\n<!-- patchworks-finding-id: finding-1 -->",
        "head_branch": "patchworks/fix-finding-1",
        "base_branch": "main"
    }

    try:
        with patch.object(github_service, "list_repository_pull_requests", return_value=[mock_pr]):
            res = client.get(f"/api/github/findings/status?workspace_id={ws_id}")
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "success"
            assert data["github_connected"] is True
            f_status = data["findings"]["finding-1"]
            assert f_status["badge_status"] == "PR OPEN"
            assert f_status["lifecycle_status"] == "pr_open"
            assert f_status["pr_number"] == 101
            assert f_status["pr_url"] == "https://github.com/testorg/testrepo/pull/101"
            assert f_status["is_open"] is True
            assert f_status["is_eligible_for_repair"] is False
            assert "Already submitted in open PR #101" in f_status["ineligibility_reason"]
    finally:
        workspace_manager.cleanup_workspace(ws_id)
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


def test_2_merged_pr_recognized_and_excluded_from_eligibility():
    finding = {
        "id": "finding-2",
        "title": "Add timeout to external API requests",
        "category": "defect",
        "severity": "medium",
        "confidence": "high",
        "files": ["app.py"],
        "line_numbers": [1],
        "explanation": "Calls block indefinitely",
        "proposed_fix": "Add timeout=10"
    }
    ws_id, temp_dir = create_git_workspace_with_findings([finding])
    fp = compute_finding_fingerprint(finding)

    mock_pr = {
        "number": 102,
        "title": "fix: add timeout to external API requests",
        "state": "closed",
        "is_merged": True,
        "merged_at": "2026-10-28T10:00:00Z",
        "closed_at": "2026-10-28T10:00:00Z",
        "html_url": "https://github.com/testorg/testrepo/pull/102",
        "body": f"## Summary\nMerged changes\n\n<!-- patchworks-finding-fingerprint: {fp} -->",
        "head_branch": "patchworks/fix-timeout",
        "base_branch": "main"
    }

    try:
        with patch.object(github_service, "list_repository_pull_requests", return_value=[mock_pr]):
            res = client.get(f"/api/github/findings/status?workspace_id={ws_id}")
            assert res.status_code == 200
            data = res.json()
            f_status = data["findings"]["finding-2"]
            assert f_status["badge_status"] == "MERGED"
            assert f_status["lifecycle_status"] == "merged"
            assert f_status["pr_number"] == 102
            assert f_status["is_merged"] is True
            assert f_status["is_eligible_for_repair"] is False
            assert "Already merged in PR #102" in f_status["ineligibility_reason"]
    finally:
        workspace_manager.cleanup_workspace(ws_id)
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


def test_3_uncertain_matches_do_not_incorrectly_suppress_finding():
    finding = {
        "id": "finding-3",
        "title": "Optimize loop performance in processing pipeline",
        "category": "performance",
        "severity": "medium",
        "confidence": "medium",
        "files": ["app.py"],
        "line_numbers": [1],
        "explanation": "Quadratic iteration detected",
        "proposed_fix": "Use hash map lookup"
    }
    ws_id, temp_dir = create_git_workspace_with_findings([finding])

    # PR mentions app.py and performance but is distinct and has no fingerprint match
    mock_pr = {
        "number": 103,
        "title": "Refactor app.py formatting and pipeline configuration",
        "state": "open",
        "is_merged": False,
        "merged_at": None,
        "closed_at": None,
        "html_url": "https://github.com/testorg/testrepo/pull/103",
        "body": "General cleanup in app.py pipeline setup.",
        "head_branch": "user-feature/pipeline-cleanup",
        "base_branch": "main"
    }

    try:
        with patch.object(github_service, "list_repository_pull_requests", return_value=[mock_pr]):
            res = client.get(f"/api/github/findings/status?workspace_id={ws_id}")
            assert res.status_code == 200
            data = res.json()
            f_status = data["findings"]["finding-3"]
            assert f_status["badge_status"] == "POSSIBLE EXISTING PR"
            assert f_status["confidence"] == "uncertain"
            assert f_status["pr_number"] == 103
            # Crucial: finding is NOT suppressed from repair eligibility!
            assert f_status["is_eligible_for_repair"] is True
    finally:
        workspace_manager.cleanup_workspace(ws_id)
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


def test_4_github_api_failures_result_in_unknown_status():
    finding = {
        "id": "finding-4",
        "title": "Validate user input encoding",
        "category": "security",
        "severity": "high",
        "confidence": "high",
        "files": ["app.py"],
        "line_numbers": [1]
    }
    ws_id, temp_dir = create_git_workspace_with_findings([finding])

    try:
        with patch.object(github_service, "list_repository_pull_requests", side_effect=ValueError("Rate limit exceeded")):
            res = client.get(f"/api/github/findings/status?workspace_id={ws_id}")
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "error"
            f_status = data["findings"]["finding-4"]
            # Must display STATUS UNKNOWN, never false negative "READY"
            assert f_status["badge_status"] == "STATUS UNKNOWN"
            assert f_status["lifecycle_status"] == "status_unknown"
            assert f_status["confidence"] == "none"
            assert "Rate limit exceeded" in f_status["ineligibility_reason"]
    finally:
        workspace_manager.cleanup_workspace(ws_id)
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


def test_5_pr_status_is_scoped_to_repository_and_user():
    finding = {
        "id": "finding-5",
        "title": "Check database connection timeout",
        "category": "defect",
        "files": ["app.py"],
        "line_numbers": [1]
    }
    ws_id, temp_dir = create_git_workspace_with_findings([finding])
    workspace_manager.update_workspace_metadata(ws_id, {"user_id": "authorized-user-uuid"})

    try:
        # Requesting without or with wrong user returns 403 Forbidden
        other_user = AuthUser(id="attacker-user-uuid", email="attacker@evil.com")
        res = client.get(
            f"/api/github/findings/status?workspace_id={ws_id}",
            headers={"Authorization": "Bearer fake_token"}
        )
        assert res.status_code == 403
    finally:
        workspace_manager.cleanup_workspace(ws_id)
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


def test_6_batch_repair_skips_ineligible_findings_by_default(monkeypatch):
    finding_ineligible = {
        "id": "f-ineligible",
        "title": "Resolved finding already submitted",
        "category": "defect",
        "files": ["app.py"],
        "line_numbers": [1]
    }
    finding_eligible = {
        "id": "f-eligible",
        "title": "Active issue to repair",
        "category": "defect",
        "files": ["app.py"],
        "line_numbers": [1]
    }
    ws_id, temp_dir = create_git_workspace_with_findings([finding_ineligible, finding_eligible])
    fp_ineligible = compute_finding_fingerprint(finding_ineligible)

    open_pr = {
        "number": 88,
        "title": "fix: resolved finding already submitted",
        "state": "open",
        "is_merged": False,
        "merged_at": None,
        "closed_at": None,
        "html_url": "https://github.com/testorg/testrepo/pull/88",
        "body": f"<!-- patchworks-finding-fingerprint: {fp_ineligible} -->",
        "head_branch": "patchworks/fix-88",
        "base_branch": "main"
    }

    valid_patch = (
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,1 +1,2 @@\n"
        " def add(a, b): return a + b\n"
        "+# repaired\n"
    )
    monkeypatch.setattr(nebius_client, "generate_patch", lambda diag, ctx: valid_patch)

    try:
        with patch.object(github_service, "list_repository_pull_requests", return_value=[open_pr]):
            res = client.post("/api/repair/batch", json={
                "workspace_id": ws_id,
                "finding_ids": ["f-ineligible", "f-eligible"]
            })
            assert res.status_code == 200
            data = res.json()
            assert data["summary"]["total"] == 2
            assert data["summary"]["skipped"] == 1
            assert data["summary"]["successful"] == 1

            r_ineligible = next(r for r in data["results"] if r["finding_id"] == "f-ineligible")
            assert r_ineligible["status"] == "skipped"
            assert "Already submitted" in r_ineligible["error"]

            r_eligible = next(r for r in data["results"] if r["finding_id"] == "f-eligible")
            assert r_eligible["status"] in ("verified", "repaired")
    finally:
        workspace_manager.cleanup_workspace(ws_id)
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


def test_7_failure_in_one_repair_does_not_corrupt_other_findings(monkeypatch):
    f1 = {"id": "f1", "title": "Good repair", "files": ["app.py"], "line_numbers": [1]}
    f2 = {"id": "f2", "title": "Bad repair", "files": ["app.py"], "line_numbers": [1]}
    ws_id, temp_dir = create_git_workspace_with_findings([f1, f2])

    patch_f1 = (
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,1 +1,2 @@\n"
        " def add(a, b): return a + b\n"
        "+# f1 patch\n"
    )

    def mock_gen_patch(diag, ctx):
        if "[Good repair]" in diag.get("root_cause", ""):
            return patch_f1
        # For f2, return invalid diff that fails apply
        return "invalid non-patch syntax"

    monkeypatch.setattr(nebius_client, "generate_patch", mock_gen_patch)

    try:
        res = client.post("/api/repair/batch", json={
            "workspace_id": ws_id,
            "finding_ids": ["f1", "f2"]
        })
        assert res.status_code == 200
        data = res.json()
        assert data["summary"]["successful"] == 1
        assert data["summary"]["failed"] == 1
        assert data["all_succeeded"] is False

        # f1 succeeded
        r1 = next(r for r in data["results"] if r["finding_id"] == "f1")
        assert r1["status"] in ("verified", "repaired")

        # f2 failed and rolled back
        r2 = next(r for r in data["results"] if r["finding_id"] == "f2")
        assert r2["status"] == "failed"

        # Verify repo working directory contains f1's commit and is clean
        ws_path = workspace_manager.get_workspace_path(ws_id)
        with open(os.path.join(ws_path, "app.py"), "r") as f:
            content = f.read()
        assert "# f1 patch" in content
    finally:
        workspace_manager.cleanup_workspace(ws_id)
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


def test_8_multiple_findings_affecting_same_file_handled_without_conflict(monkeypatch):
    f1 = {"id": "f1", "title": "First fix in app.py", "files": ["app.py"], "line_numbers": [1]}
    f2 = {"id": "f2", "title": "Second fix in app.py", "files": ["app.py"], "line_numbers": [1]}
    ws_id, temp_dir = create_git_workspace_with_findings([f1, f2])

    def mock_gen_patch(diag, ctx):
        if "[First fix in app.py]" in diag.get("root_cause", ""):
            return (
                "--- a/app.py\n"
                "+++ b/app.py\n"
                "@@ -1,1 +1,2 @@\n"
                " def add(a, b): return a + b\n"
                "+# change from f1\n"
            )
        else:
            # f2 sees updated file containing # change from f1
            assert "# change from f1" in ctx
            return (
                "--- a/app.py\n"
                "+++ b/app.py\n"
                "@@ -1,2 +1,3 @@\n"
                " def add(a, b): return a + b\n"
                " # change from f1\n"
                "+# change from f2\n"
            )

    monkeypatch.setattr(nebius_client, "generate_patch", mock_gen_patch)

    try:
        res = client.post("/api/repair/batch", json={
            "workspace_id": ws_id,
            "finding_ids": ["f1", "f2"]
        })
        assert res.status_code == 200
        data = res.json()
        assert data["all_succeeded"] is True
        assert data["summary"]["successful"] == 2
        assert data["summary"]["failed"] == 0

        # Verify both changes exist in workspace app.py
        ws_path = workspace_manager.get_workspace_path(ws_id)
        with open(os.path.join(ws_path, "app.py"), "r") as f:
            content = f.read()
        assert "# change from f1" in content
        assert "# change from f2" in content
    finally:
        workspace_manager.cleanup_workspace(ws_id)
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


def test_9_failed_tests_prevent_finding_from_being_marked_verified(monkeypatch):
    f = {"id": "f1", "title": "Fix that breaks test", "files": ["app.py"], "line_numbers": [1]}
    # Test file that will fail
    ws_id, temp_dir = create_git_workspace_with_findings([f], test_content="def test_fail(): assert 1 == 2\n")

    patch_code = (
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,1 +1,2 @@\n"
        " def add(a, b): return a + b\n"
        "+# test breaker\n"
    )
    monkeypatch.setattr(nebius_client, "generate_patch", lambda diag, ctx: patch_code)

    try:
        res = client.post("/api/repair/batch", json={
            "workspace_id": ws_id,
            "finding_ids": ["f1"],
            "test_command": "pytest test_app.py"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["all_succeeded"] is False
        r1 = data["results"][0]
        assert r1["status"] == "rolled_back"
        assert r1["verification_status"] == "FIX FAILED"
        assert r1["test_details"]["returncode"] != 0

        # Ensure changes were rolled back
        ws_path = workspace_manager.get_workspace_path(ws_id)
        with open(os.path.join(ws_path, "app.py"), "r") as fl:
            content = fl.read()
        assert "# test breaker" not in content
    finally:
        workspace_manager.cleanup_workspace(ws_id)
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


def test_10_batch_completion_accurately_reports_partial_failures_and_skipped(monkeypatch):
    f_skip = {"id": "f_skip", "title": "Skipped finding", "files": ["app.py"], "line_numbers": [1]}
    f_ok = {"id": "f_ok", "title": "OK finding", "files": ["app.py"], "line_numbers": [1]}
    f_fail = {"id": "f_fail", "title": "Fail finding", "files": ["app.py"], "line_numbers": [1]}
    ws_id, temp_dir = create_git_workspace_with_findings([f_skip, f_ok, f_fail])

    # Mark f_skip as merged
    fp_skip = compute_finding_fingerprint(f_skip)
    mock_merged_pr = {
        "number": 55,
        "title": "fix: skipped finding",
        "state": "closed",
        "is_merged": True,
        "merged_at": "2026-10-28T09:00:00Z",
        "closed_at": "2026-10-28T09:00:00Z",
        "html_url": "https://github.com/testorg/testrepo/pull/55",
        "body": f"<!-- patchworks-finding-fingerprint: {fp_skip} -->",
        "head_branch": "patchworks/fix-55",
        "base_branch": "main"
    }

    def mock_gen_patch(diag, ctx):
        if "[OK finding]" in diag.get("root_cause", ""):
            return "--- a/app.py\n+++ b/app.py\n@@ -1,1 +1,2 @@\n def add(a, b): return a + b\n+# ok\n"
        return "broken patch"

    monkeypatch.setattr(nebius_client, "generate_patch", mock_gen_patch)

    try:
        with patch.object(github_service, "list_repository_pull_requests", return_value=[mock_merged_pr]):
            res = client.post("/api/repair/batch", json={
                "workspace_id": ws_id,
                "finding_ids": ["f_skip", "f_ok", "f_fail"]
            })
            assert res.status_code == 200
            data = res.json()
            assert data["all_succeeded"] is False
            assert data["status"] == "partial_success"
            assert data["summary"] == {
                "total": 3,
                "successful": 1,
                "failed": 1,
                "skipped": 1
            }
    finally:
        workspace_manager.cleanup_workspace(ws_id)
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


def test_11_duplicate_pr_creation_prevented_for_confidently_matched_repairs():
    finding = {"id": "f_dup", "title": "Prevent duplicate PR issue", "files": ["app.py"], "line_numbers": [1]}
    ws_id, temp_dir = create_git_workspace_with_findings([finding])
    fp = compute_finding_fingerprint(finding)

    # Set workspace verification status to FIX VERIFIED so gate checks reach duplicate PR validation
    workspace_manager.update_workspace_metadata(ws_id, {
        "verification_status": "FIX VERIFIED",
        "selected_finding": finding
    })

    open_pr = {
        "number": 99,
        "title": "fix: prevent duplicate PR issue",
        "state": "open",
        "is_merged": False,
        "merged_at": None,
        "closed_at": None,
        "html_url": "https://github.com/testorg/testrepo/pull/99",
        "body": f"<!-- patchworks-finding-fingerprint: {fp} -->",
        "head_branch": "patchworks/fix-99",
        "base_branch": "main"
    }

    try:
        with patch.object(github_service, "list_repository_pull_requests", return_value=[open_pr]):
            # 1. Readiness returns ready: False with existing PR explanation
            readiness = client.get(f"/api/github/publish/readiness?workspace_id={ws_id}")
            assert readiness.status_code == 200
            r_data = readiness.json()
            assert r_data["ready"] is False
            assert "A pull request (#99) has already been submitted" in r_data["reason"]
            assert r_data["existing_pr"]["pr_number"] == 99

            # 2. Publish raises 409 Conflict
            pub_res = client.post("/api/github/publish", json={
                "workspace_id": ws_id,
                "title": "fix: prevent duplicate PR issue"
            })
            assert pub_res.status_code == 409
            assert "Duplicate PR prevented: Pull request #99 is already open" in pub_res.json()["detail"]
    finally:
        workspace_manager.cleanup_workspace(ws_id)
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


def test_12_existing_individual_repair_verification_and_publish_workflows_work(monkeypatch):
    finding = {"id": "f_std", "title": "Standard single repair", "files": ["app.py"], "line_numbers": [1]}
    ws_id, temp_dir = create_git_workspace_with_findings([finding])

    valid_patch = (
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,1 +1,2 @@\n"
        " def add(a, b): return a + b\n"
        "+# single repair verified\n"
    )
    monkeypatch.setattr(nebius_client, "generate_patch", lambda diag, ctx: valid_patch)

    try:
        # 1. Individual repair
        repair_res = client.post("/api/repair", json={
            "workspace_id": ws_id,
            "issue_description": "fix standard issue",
            "selected_finding": finding,
            "test_command": "pytest test_app.py"
        })
        assert repair_res.status_code == 200
        rep_data = repair_res.json()
        assert rep_data["patch_applied"] is True
        assert rep_data["verification_status"] == "FIX VERIFIED"

        # 2. Publish readiness
        with patch.object(github_service, "list_repository_pull_requests", return_value=[]), \
             patch.object(github_service, "check_divergence", return_value=(False, "head_sha")):
            readiness = client.get(f"/api/github/publish/readiness?workspace_id={ws_id}")
            assert readiness.status_code == 200
            assert readiness.json()["ready"] is True

            # 3. Publish PR
            mock_pr_res = {
                "status": "success",
                "pr_url": "https://github.com/testorg/testrepo/pull/120",
                "pr_number": 120,
                "branch": "patchworks/fix-std",
                "commit_sha": "abcd1234ef",
                "target_branch": "main"
            }
            with patch.object(github_service, "publish_pull_request", return_value=mock_pr_res):
                pub_res = client.post("/api/github/publish", json={
                    "workspace_id": ws_id,
                    "title": "fix: standard single repair"
                })
                assert pub_res.status_code == 200
                assert pub_res.json()["pr_number"] == 120
    finally:
        workspace_manager.cleanup_workspace(ws_id)
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


def test_13_batch_repair_rollback_cannot_discard_unrelated_workspace_changes(monkeypatch):
    f_fail = {"id": "f_fail", "title": "Failing repair", "files": ["app.py"], "line_numbers": [1]}
    f_good = {"id": "f_good", "title": "Good repair", "files": ["app.py"], "line_numbers": [1]}
    ws_id, temp_dir = create_git_workspace_with_findings([f_fail, f_good])
    ws_path = workspace_manager.get_workspace_path(ws_id)

    # 1. Create an unrelated untracked user file in the workspace
    unrelated_file = os.path.join(ws_path, "user_notes.txt")
    with open(unrelated_file, "w") as f:
        f.write("Important developer notes: do not delete")

    # 2. Modify an existing file with unrelated uncommitted changes
    feature_file = os.path.join(ws_path, "unrelated_feature.py")
    with open(feature_file, "w") as f:
        f.write("# WIP feature work\n")

    def mock_gen_patch(diag, ctx):
        if "[Failing repair]" in diag.get("root_cause", ""):
            # Bad patch that fails apply or verification
            return "broken invalid diff syntax"
        elif "[Good repair]" in diag.get("root_cause", ""):
            return (
                "--- a/app.py\n"
                "+++ b/app.py\n"
                "@@ -1,1 +1,2 @@\n"
                " def add(a, b): return a + b\n"
                "+# good repair applied\n"
            )
        return ""

    monkeypatch.setattr(nebius_client, "generate_patch", mock_gen_patch)

    try:
        res = client.post("/api/repair/batch", json={
            "workspace_id": ws_id,
            "finding_ids": ["f_fail", "f_good"]
        })
        assert res.status_code == 200
        data = res.json()
        assert data["summary"]["successful"] == 1
        assert data["summary"]["failed"] == 1

        # 3. CRITICAL VERIFICATION:
        # The unrelated untracked file MUST NOT be deleted by rollback
        assert os.path.exists(unrelated_file), "Unrelated user notes file was discarded by batch rollback!"
        with open(unrelated_file, "r") as f:
            assert f.read() == "Important developer notes: do not delete"

        # The unrelated feature file MUST NOT be deleted by rollback
        assert os.path.exists(feature_file), "Unrelated feature file was discarded by batch rollback!"
        with open(feature_file, "r") as f:
            assert "# WIP feature work" in f.read()

        # The good repair must be present in app.py
        with open(os.path.join(ws_path, "app.py"), "r") as f:
            app_content = f.read()
        assert "# good repair applied" in app_content
    finally:
        workspace_manager.cleanup_workspace(ws_id)
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

