import pytest
import re
from backend.app.reporting import (
    format_pull_request_body,
    format_commit_message,
    format_commit_title,
    format_pr_title,
    strip_emojis,
    redact_secrets,
    clean_prose,
    EMOJI_PATTERN
)

def test_pr_body_contains_zero_emojis():
    """Verify that PR descriptions strip all emojis and decorative symbols."""
    body = format_pull_request_body(
        title="🛠️ Fix critical null pointer bug 🚀",
        problem_summary="⚠️ Observed crash in auth service 🔥",
        diagnosis_data={
            "diagnosis": "🔍 Missing check for None in session token validation 💥",
            "evidence": "if session.token is None: raise Error",
            "files_to_modify": ["auth/service.py"],
            "proposed_fix_description": "⚡ Add defensive guard check ✅",
            "regression_risks": "⚠️ Low risk under standard authentication suite."
        },
        verification_details={
            "returncode": 0,
            "success": True,
            "stdout": "test_auth_guard PASSED [100%]"
        },
        model_name="nvidia/llama-3.1-nemotron-70b-instruct",
        is_mock_mode=False,
        new_branch="patchworks/fix-auth",
        target_branch="main",
        commit_sha="1234567890abcdef",
        custom_notes="📝 Verified by test runner 🎉"
    )

    emojis_found = EMOJI_PATTERN.findall(body)
    assert len(emojis_found) == 0, f"Found emojis in PR body: {emojis_found}"
    assert "🛠️" not in body
    assert "🚀" not in body
    assert "🔥" not in body
    assert "⚡" not in body
    assert "🔍" not in body
    assert "📝" not in body

def test_pr_body_sentence_case_and_clean_headings():
    """Verify standard sentence case headings without ornamental dividers."""
    body = format_pull_request_body(
        title="Fix boundary check in string truncation",
        problem_summary="Text utility cuts off strings of exact maximum length.",
        diagnosis_data={
            "diagnosis": "Condition checked >= instead of >.",
            "evidence": "if len(text) >= max_length: return text[:max_length] + '...'",
            "files_to_modify": ["utils/text.py"],
            "proposed_fix_description": "Change comparison operator to >.",
            "regression_risks": "Low risk. Corrects boundary behavior for exact-length strings."
        },
        verification_details={
            "returncode": 0,
            "success": True,
            "stdout": "test_truncate PASSED"
        },
        model_name="nvidia/Nemotron-3_5-Lightning",
        is_mock_mode=False,
        new_branch="patchworks/fix-truncate",
        target_branch="main",
        commit_sha="a1b2c3d4e5f67890"
    )

    # Check required sentence case headings
    assert "## Summary" in body
    assert "## Root cause" in body
    assert "## Changes" in body
    assert "## Verification" in body
    assert "## Risk assessment" in body

    # Must not contain ornamental headers or repeated divider rules
    assert "## 🛠️ Patchworks Verified Code Repair" not in body
    assert "### 📋 Overview" not in body
    assert "### 🔍 Root Cause Diagnosis" not in body
    assert "### 🧪 Empirical Verification Results" not in body

def test_pr_body_truthful_verification_success():
    """Verify passing test outcomes report FIX VERIFIED and exit code 0."""
    body = format_pull_request_body(
        title="Fix math subtraction",
        problem_summary="Subtract function performs addition.",
        diagnosis_data={
            "diagnosis": "Operator typo in math_utils.py.",
            "files_to_modify": ["math_utils.py"]
        },
        verification_details={
            "returncode": 0,
            "success": True,
            "stdout": "test_subtract PASSED"
        },
        model_name="test_model",
        is_mock_mode=True,
        new_branch="patchworks/fix-math",
        target_branch="main",
        commit_sha="112233445566"
    )

    assert "FIX VERIFIED" in body
    assert "- **Exit code:** `0`" in body
    assert "test_subtract PASSED" in body
    assert "FIX FAILED" not in body
    assert "UNVERIFIED" not in body

def test_pr_body_truthful_verification_failure():
    """Verify failed tests cannot be reported as verified."""
    body = format_pull_request_body(
        title="Fix math subtraction",
        problem_summary="Subtract function performs addition.",
        diagnosis_data={"diagnosis": "Operator typo"},
        verification_details={
            "returncode": 1,
            "success": False,
            "stdout": "test_subtract FAILED",
            "stderr": "AssertionError: 3 != -1"
        },
        model_name="test_model",
        is_mock_mode=True,
        new_branch="patchworks/fix-math",
        target_branch="main",
        commit_sha="112233445566"
    )

    assert "FIX FAILED" in body
    assert "- **Exit code:** `1`" in body
    assert "AssertionError: 3 != -1" in body
    assert "FIX VERIFIED" not in body

def test_pr_body_truthful_verification_incomplete():
    """Verify test timeout or execution failure is reported as incomplete."""
    body = format_pull_request_body(
        title="Fix timeout bug",
        problem_summary="Infinite loop in parser.",
        diagnosis_data={"diagnosis": "Missing loop increment"},
        verification_details={
            "returncode": -1,
            "success": False,
            "stderr": "Test execution timed out after 30 seconds"
        },
        model_name="test_model",
        is_mock_mode=True,
        new_branch="patchworks/fix-loop",
        target_branch="main",
        commit_sha="112233445566"
    )

    assert "VERIFICATION INCOMPLETE" in body
    assert "FIX VERIFIED" not in body

def test_pr_body_truthful_verification_unexecuted():
    """Verify unexecuted tests explicitly state UNVERIFIED and never imply success."""
    body = format_pull_request_body(
        title="Fix config setting",
        problem_summary="Updated port configuration.",
        diagnosis_data={"diagnosis": "Port changed to 8080"},
        verification_details=None,
        model_name="test_model",
        is_mock_mode=False,
        new_branch="patchworks/fix-config",
        target_branch="main",
        commit_sha="112233445566"
    )

    assert "UNVERIFIED" in body
    assert "no automated test suite was executed" in body
    assert "FIX VERIFIED" not in body

def test_pr_body_omits_empty_sections():
    """Verify empty sections are omitted rather than filled with boilerplate."""
    body = format_pull_request_body(
        title="Update configuration",
        problem_summary="Adjusted timeout parameter.",
        diagnosis_data={
            "diagnosis": "Timeout was too short for large payloads.",
            # No files_to_modify and no regression_risks
            "files_to_modify": [],
            "regression_risks": ""
        },
        verification_details={
            "returncode": 0,
            "success": True,
            "stdout": "PASSED"
        },
        model_name="test_model",
        is_mock_mode=True,
        new_branch="patchworks/fix-timeout",
        target_branch="main",
        commit_sha="112233445566"
    )

    # Changes section should be omitted if no files were specified
    assert "## Changes" not in body
    # Root cause and Verification should still be present
    assert "## Root cause" in body
    assert "## Verification" in body

def test_pr_body_uncertain_diagnosis():
    """Verify uncertain root causes are clearly stated."""
    body = format_pull_request_body(
        title="Investigate intermittent failure",
        problem_summary="Intermittent test failure on CI.",
        diagnosis_data={
            "diagnosis": "Unknown: root cause cannot evaluate without full trace logs.",
            "evidence": "",
            "files_to_modify": []
        },
        verification_details=None,
        model_name="test_model",
        is_mock_mode=True,
        new_branch="patchworks/investigate",
        target_branch="main",
        commit_sha="112233445566"
    )

    assert "## Root cause" in body
    assert "cannot evaluate" in body.lower() or "not definitively confirmed" in body.lower()

def test_pr_body_absence_of_promotional_footers():
    """Verify that marketing slogans and promotional footers are absent."""
    body = format_pull_request_body(
        title="Fix calculation",
        problem_summary="Tax computation rounding defect.",
        diagnosis_data={
            "diagnosis": "Rounding defect",
            "files_to_modify": ["tax.py"],
            "regression_risks": "Low risk"
        },
        verification_details={"returncode": 0, "stdout": "OK"},
        model_name="nvidia/Nemotron-3_5-Lightning",
        is_mock_mode=False,
        new_branch="patchworks/fix-tax",
        target_branch="main",
        commit_sha="12345678"
    )

    assert "Created autonomously with" not in body
    assert "Find the fault. Forge the fix. Prove it works." not in body
    assert "Official Autonomous Code-Repair Audit Report" not in body
    assert "Patchworks Verified Code Repair" not in body

def test_pr_body_redacts_secrets_in_logs_and_prose():
    """Verify sensitive tokens and keys are redacted from logs and prose."""
    secret_token = "ghp_1234567890abcdefghijklmnopqrstuv"
    secret_key = "sk-nebius-123456789012345678901234"
    auth_header = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"

    body = format_pull_request_body(
        title=f"Fix auth with {secret_token}",
        problem_summary=f"Failed with Authorization: {auth_header}",
        diagnosis_data={
            "diagnosis": f"Client attempted request with {secret_key}",
            "evidence": f"auth_token = '{secret_token}'",
            "files_to_modify": ["client.py"]
        },
        verification_details={
            "returncode": 0,
            "stdout": f"Authenticated using {secret_token} and {secret_key}"
        },
        model_name="test_model",
        is_mock_mode=False,
        new_branch="patchworks/fix-auth",
        target_branch="main",
        commit_sha="12345678"
    )

    assert secret_token not in body
    assert secret_key not in body
    assert "eyJhbGci" not in body
    assert "[REDACTED" in body

def test_pr_body_preserves_technical_details_and_code():
    """Verify that filenames, paths, exit codes, and stdout are intact."""
    body = format_pull_request_body(
        title="Fix division by zero in metrics calculator",
        problem_summary="ZeroDivisionError when calculating request latency percentiles.",
        diagnosis_data={
            "diagnosis": "Denominator count is 0 when dataset is empty.",
            "evidence": "def p99(latencies):\n    return latencies[int(len(latencies)*0.99)] / len(latencies)",
            "files_to_modify": ["src/metrics/latency_calculator.py"],
            "proposed_fix_description": "Return 0.0 early if latencies list is empty.",
            "regression_risks": "Low risk. Only affects empty input handling."
        },
        verification_details={
            "returncode": 0,
            "success": True,
            "stdout": "pytest src/metrics/test_latency.py -v\ntest_empty_latency PASSED\ntest_p99 PASSED"
        },
        model_name="nvidia/llama-3.1-nemotron-70b-instruct",
        is_mock_mode=False,
        new_branch="patchworks/fix-latency",
        target_branch="main",
        commit_sha="deadbeef12345678"
    )

    assert "src/metrics/latency_calculator.py" in body
    assert "ZeroDivisionError" in body
    assert "test_empty_latency PASSED" in body
    assert "patchworks/fix-latency" in body
    assert "- **Exit code:** `0`" in body

def test_commit_message_and_title_helpers():
    """Verify commit message and PR title helpers conform to professional standards."""
    # Commit message with emoji and trailing period
    commit_msg = format_commit_message(
        title="🛠️ fix off-by-one error in truncate function. 🚀",
        summary="Adjusts condition from >= to > so exact-length strings are preserved."
    )
    assert not EMOJI_PATTERN.search(commit_msg)
    assert commit_msg.startswith("fix: ")
    assert "Adjusts condition from >= to >" in commit_msg
    assert "Autonomously repaired" not in commit_msg

    # PR title helper
    pr_title = format_pr_title("🚀 Add defensive validation check for null sessions. ✨")
    assert not EMOJI_PATTERN.search(pr_title)
    assert pr_title == "Add defensive validation check for null sessions"
