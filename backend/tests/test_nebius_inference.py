import os
import json
import pytest
from unittest.mock import MagicMock, patch
from openai import (
    AuthenticationError,
    NotFoundError,
    RateLimitError,
    APITimeoutError,
    APIConnectionError,
    APIStatusError,
)
import httpx

from backend.app.nebius_client import (
    NebiusClient,
    NebiusInferenceError,
    format_api_error,
    extract_unified_diff
)

def test_config_loading_defaults(monkeypatch):
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    monkeypatch.delenv("NEBIUS_BASE_URL", raising=False)
    monkeypatch.delenv("NEBIUS_MODEL_NAME", raising=False)

    client = NebiusClient(api_key="mock_key")
    assert client.mock_mode is True
    assert client.base_url == "https://api.studio.nebius.ai/v1/"
    assert client.model_name == "nvidia/Nemotron-3_5-Lightning"
    assert client.client is None

def test_config_loading_custom_env(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "test_key_123")
    monkeypatch.setenv("NEBIUS_BASE_URL", "https://custom.nebius.api/v1/")
    monkeypatch.setenv("NEBIUS_MODEL_NAME", "nvidia/Nemotron-3_5-Lightning")

    client = NebiusClient()
    assert client.mock_mode is False
    assert client.base_url == "https://custom.nebius.api/v1/"
    assert client.model_name == "nvidia/Nemotron-3_5-Lightning"
    assert client.client is not None

def test_mock_mode_detection(monkeypatch):
    # Various mock key formats
    assert NebiusClient(api_key="mock_key").mock_mode is True
    assert NebiusClient(api_key="").mock_mode is True

    # When no key is in env
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    assert NebiusClient(api_key=None).mock_mode is True

    # Real key format
    client = NebiusClient(api_key="v1.statickey-test-token")
    assert client.mock_mode is False
    assert client.client is not None

def test_mock_diagnose_and_generate_patch():
    client = NebiusClient(api_key="mock_key")
    
    # simple_bug fixture
    code_ctx = "def subtract(a: int, b: int) -> int:\n    return a + b\n"
    diag = client.diagnose("test_subtract fails", f"--- math_utils.py ---\n{code_ctx}")
    assert "[SIMULATED MOCK]" in diag["diagnosis"]
    assert "math_utils.py" in diag["files_to_modify"]

    patch = client.generate_patch(diag, f"--- math_utils.py ---\n{code_ctx}")
    assert "--- a/math_utils.py" in patch
    assert "+++ b/math_utils.py" in patch
    assert "-    return a + b" in patch
    assert "+    return a - b" in patch

def test_extract_unified_diff():
    # Raw diff without markdown
    raw_diff = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n"
    assert extract_unified_diff(raw_diff).strip() == raw_diff.strip()

    # Markdown wrapped in ```diff
    markdown_diff = f"Here is the diff:\n```diff\n{raw_diff}```\nHope this helps!"
    assert extract_unified_diff(markdown_diff).strip() == raw_diff.strip()

    # Markdown wrapped in generic ```
    generic_diff = f"```\n{raw_diff}```"
    assert extract_unified_diff(generic_diff).strip() == raw_diff.strip()

def test_live_diagnose_success():
    client = NebiusClient(api_key="dummy_real_key")
    mock_openai = MagicMock()
    client.client = mock_openai

    fake_json = {
        "diagnosis": "Off-by-one boundary error in loop.",
        "evidence": "i < len(items) - 1",
        "files_to_modify": ["processor.py"],
        "proposed_fix_description": "Change to i < len(items)",
        "regression_risks": "Low risk"
    }

    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps(fake_json)
    mock_openai.chat.completions.create.return_value = MagicMock(choices=[mock_choice])

    result = client.diagnose("Loop terminates too early", "def process(): pass")
    assert result["diagnosis"] == "Off-by-one boundary error in loop."
    assert result["files_to_modify"] == ["processor.py"]

    # Verify model parameter passed
    args, kwargs = mock_openai.chat.completions.create.call_args
    assert kwargs["model"] == "nvidia/Nemotron-3_5-Lightning"

def test_live_generate_patch_success():
    client = NebiusClient(api_key="dummy_real_key")
    mock_openai = MagicMock()
    client.client = mock_openai

    mock_diff = "--- a/processor.py\n+++ b/processor.py\n@@ -1 +1 @@\n-old\n+new\n"
    mock_choice = MagicMock()
    mock_choice.message.content = f"```diff\n{mock_diff}```"
    mock_openai.chat.completions.create.return_value = MagicMock(choices=[mock_choice])

    patch = client.generate_patch({"diagnosis": "test"}, "code context")
    assert "--- a/processor.py" in patch
    assert "+new" in patch

def test_live_api_failure_raises_error_without_mock_fallback():
    client = NebiusClient(api_key="dummy_real_key")
    mock_openai = MagicMock()
    client.client = mock_openai

    # Simulate 401 AuthenticationError
    req = httpx.Request("POST", "https://api.studio.nebius.ai/v1/chat/completions")
    resp = httpx.Response(401, request=req)
    mock_openai.chat.completions.create.side_effect = AuthenticationError(
        message="Invalid API Key", response=resp, body=None
    )

    # In live mode, failure must raise NebiusInferenceError and NOT return mock diagnosis
    with pytest.raises(NebiusInferenceError) as exc_info:
        client.diagnose("Issue", "Code")
    assert "authentication failed" in str(exc_info.value).lower()
    assert "[SIMULATED MOCK]" not in str(exc_info.value)

    # Simulate 404 NotFoundError
    resp_404 = httpx.Response(404, request=req)
    mock_openai.chat.completions.create.side_effect = NotFoundError(
        message="Model not found", response=resp_404, body=None
    )

    with pytest.raises(NebiusInferenceError) as exc_info404:
        client.generate_patch({"diagnosis": "test"}, "Code")
    assert "not found" in str(exc_info404.value).lower()

    # Simulate 429 RateLimitError
    resp_429 = httpx.Response(429, request=req)
    mock_openai.chat.completions.create.side_effect = RateLimitError(
        message="Rate limit exceeded", response=resp_429, body=None
    )

    with pytest.raises(NebiusInferenceError) as exc_info429:
        client.diagnose("Issue", "Code")
    assert "rate limit" in str(exc_info429.value).lower()

def test_format_api_error_diagnostics():
    req = httpx.Request("POST", "https://api.studio.nebius.ai/v1/chat/completions")
    
    err401 = AuthenticationError("Unauthorized", response=httpx.Response(401, request=req), body=None)
    msg401 = format_api_error(err401, "test-model", "https://api.studio.nebius.ai/v1/")
    assert "401" in msg401
    assert "NEBIUS_API_KEY" in msg401

    err404 = NotFoundError("Not Found", response=httpx.Response(404, request=req), body=None)
    msg404 = format_api_error(err404, "nvidia/Nemotron-3_5-Lightning", "https://api.studio.nebius.ai/v1/")
    assert "404" in msg404
    assert "nvidia/Nemotron-3_5-Lightning" in msg404

def test_extract_json_surrounded_by_fences():
    from backend.app.nebius_client import extract_json_object

    fenced_content = """Here is the diagnostic result:
```json
{
  "diagnosis": "Function fails on zero division.",
  "evidence": "return a / b",
  "files_to_modify": ["math.py"],
  "proposed_fix_description": "Check if b == 0",
  "regression_risks": "Low"
}
```
Please let me know if you need more details."""

    data = extract_json_object(fenced_content)
    assert data["diagnosis"] == "Function fails on zero division."
    assert data["files_to_modify"] == ["math.py"]

def test_extract_json_unfenced_with_surrounding_commentary():
    from backend.app.nebius_client import extract_json_object

    text = """Certainly!
{
  "summary": "Repository code review",
  "findings": [{"id": "1", "title": "Cache invalidation"}]
}
Hope this was helpful!"""

    data = extract_json_object(text)
    assert data["summary"] == "Repository code review"
    assert len(data["findings"]) == 1

def test_inference_empty_message_content_raises_error():
    client = NebiusClient(api_key="dummy_real_key")
    mock_openai = MagicMock()
    client.client = mock_openai

    mock_choice = MagicMock()
    mock_choice.message.content = ""
    mock_choice.message.reasoning = ""
    mock_choice.finish_reason = "stop"
    mock_choice.message.refusal = None
    mock_openai.chat.completions.create.return_value = MagicMock(choices=[mock_choice])

    with pytest.raises(NebiusInferenceError) as exc_info:
        client.diagnose("Issue", "Code")
    assert "empty response" in str(exc_info.value).lower()

def test_inference_missing_choices_raises_error():
    client = NebiusClient(api_key="dummy_real_key")
    mock_openai = MagicMock()
    client.client = mock_openai

    mock_openai.chat.completions.create.return_value = MagicMock(choices=[])

    with pytest.raises(NebiusInferenceError) as exc_info:
        client.diagnose("Issue", "Code")
    assert "0 completion choices" in str(exc_info.value).lower()

def test_inference_truncated_output_finish_reason_length():
    client = NebiusClient(api_key="dummy_real_key")
    mock_openai = MagicMock()
    client.client = mock_openai

    mock_choice = MagicMock()
    mock_choice.message.content = None
    mock_choice.message.reasoning = None
    mock_choice.finish_reason = "length"
    mock_choice.message.refusal = None
    mock_openai.chat.completions.create.return_value = MagicMock(choices=[mock_choice])

    with pytest.raises(NebiusInferenceError) as exc_info:
        client.diagnose("Issue", "Code")
    assert "token limit" in str(exc_info.value).lower() or "finish_reason: length" in str(exc_info.value).lower()

def test_inference_model_refusal_raises_error():
    client = NebiusClient(api_key="dummy_real_key")
    mock_openai = MagicMock()
    client.client = mock_openai

    mock_choice = MagicMock()
    mock_choice.message.content = None
    mock_choice.message.refusal = "I cannot fulfill this request due to safety policies."
    mock_openai.chat.completions.create.return_value = MagicMock(choices=[mock_choice])

    with pytest.raises(NebiusInferenceError) as exc_info:
        client.diagnose("Issue", "Code")
    assert "refused" in str(exc_info.value).lower()

def test_inference_content_filter_raises_error():
    client = NebiusClient(api_key="dummy_real_key")
    mock_openai = MagicMock()
    client.client = mock_openai

    mock_choice = MagicMock()
    mock_choice.message.content = None
    mock_choice.finish_reason = "content_filter"
    mock_choice.message.refusal = None
    mock_openai.chat.completions.create.return_value = MagicMock(choices=[mock_choice])

    with pytest.raises(NebiusInferenceError) as exc_info:
        client.diagnose("Issue", "Code")
    assert "content safety" in str(exc_info.value).lower()

def test_inference_5xx_and_timeout_errors():
    client = NebiusClient(api_key="dummy_real_key")
    mock_openai = MagicMock()
    client.client = mock_openai

    req = httpx.Request("POST", "https://api.studio.nebius.ai/v1/chat/completions")
    
    # 500 APIStatusError
    resp_500 = httpx.Response(500, request=req)
    mock_openai.chat.completions.create.side_effect = APIStatusError(
        message="Internal Server Error", response=resp_500, body=None
    )
    with pytest.raises(NebiusInferenceError) as exc_info500:
        client.diagnose("Issue", "Code")
    assert "500" in str(exc_info500.value)

    # APITimeoutError
    mock_openai.chat.completions.create.side_effect = APITimeoutError(request=req)
    with pytest.raises(NebiusInferenceError) as exc_timeout:
        client.diagnose("Issue", "Code")
    assert "timed out" in str(exc_timeout.value).lower() or "timeout" in str(exc_timeout.value).lower()

def test_inference_malformed_json_raises_error():
    client = NebiusClient(api_key="dummy_real_key")
    mock_openai = MagicMock()
    client.client = mock_openai

    mock_choice = MagicMock()
    mock_choice.message.content = "Not a JSON at all! {unclosed"
    mock_choice.finish_reason = "stop"
    mock_choice.message.refusal = None
    mock_openai.chat.completions.create.return_value = MagicMock(choices=[mock_choice])

    with pytest.raises(NebiusInferenceError) as exc_info:
        client.diagnose("Issue", "Code")
    assert "malformed" in str(exc_info.value).lower() or "json" in str(exc_info.value).lower()

def test_error_messages_do_not_expose_secrets():
    secret_key = "v1.statickey-SUPER_SECRET_TOKEN_XYZ12345"
    client = NebiusClient(api_key=secret_key)
    mock_openai = MagicMock()
    client.client = mock_openai

    req = httpx.Request(
        "POST", 
        "https://api.studio.nebius.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {secret_key}"}
    )
    resp = httpx.Response(401, request=req, text=f"Token {secret_key} is invalid")
    err = AuthenticationError("Unauthorized", response=resp, body=None)

    msg = format_api_error(err, "nvidia/Nemotron-3_5-Lightning", "https://api.studio.nebius.ai/v1/")
    assert secret_key not in msg
    assert "SUPER_SECRET" not in msg

def test_investigate_mock_and_live():
    client = NebiusClient(api_key="mock_key")
    profile = {
        "languages": ["TypeScript", "JavaScript"],
        "manifests": ["package.json"],
        "test_command": "npm test",
        "readme_summary": "EasyType editor plugin"
    }

    # Mock investigate
    res = client.investigate("improvement", "gimme some ways to improve it", profile, "function edit() {}")
    assert "findings" in res
    assert len(res["findings"]) > 0
    assert "summary" in res

    # Live investigate with mocked openai client
    live_client = NebiusClient(api_key="dummy_real_key")
    mock_openai = MagicMock()
    live_client.client = mock_openai

    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps({
        "summary": "Repository analysis completed with 2 findings.",
        "findings": [
            {
                "id": "finding-1",
                "title": "Decouple AST parser from keystroke handler",
                "category": "performance",
                "severity": "high",
                "confidence": "high",
                "impact": "Eliminate input latency",
                "risk": "Low",
                "files": ["extension.js"],
                "evidence": "onKeyPress(() => parseAST())",
                "explanation": "Synchronous parsing on every keystroke blocks UI.",
                "proposed_fix": "Debounce AST parsing."
            }
        ]
    })
    mock_choice.finish_reason = "stop"
    mock_choice.message.refusal = None
    mock_openai.chat.completions.create.return_value = MagicMock(choices=[mock_choice])

    live_res = live_client.investigate("improvement", "gimme some ways to improve it", profile, "function edit() {}")
    assert len(live_res["findings"]) == 1
    assert live_res["findings"][0]["title"] == "Decouple AST parser from keystroke handler"

def test_timeout_handling_never_retries():
    """Verify that an APITimeoutError fails fast without retrying and raises NebiusInferenceError."""
    client = NebiusClient(api_key="dummy_real_key", timeout=30.0)
    mock_openai = MagicMock()
    client.client = mock_openai

    req = httpx.Request("POST", "https://api.studio.nebius.ai/v1/chat/completions")
    mock_openai.chat.completions.create.side_effect = APITimeoutError(request=req)

    with pytest.raises(NebiusInferenceError) as exc_info:
        client.investigate(
            intent="improvement",
            issue_description="improve code",
            project_profile={"languages": ["Python"], "manifests": [], "test_command": "", "readme_summary": ""},
            code_context="def foo(): pass"
        )

    # Exactly 1 attempt made — NEVER retried
    assert mock_openai.chat.completions.create.call_count == 1
    err_text = str(exc_info.value).lower()
    assert "timed out" in err_text
    assert "30.0s" in err_text or "deadline" in err_text

def test_transient_retry_success():
    """Verify transient error (e.g. 503) is retried at most once and succeeds on 2nd attempt."""
    client = NebiusClient(api_key="dummy_real_key")
    mock_openai = MagicMock()
    client.client = mock_openai

    req = httpx.Request("POST", "https://api.studio.nebius.ai/v1/chat/completions")
    resp_503 = httpx.Response(503, request=req)
    error_503 = APIStatusError(message="Service Unavailable", response=resp_503, body=None)

    success_choice = MagicMock()
    success_choice.message.content = json.dumps({"summary": "OK", "findings": []})
    success_choice.finish_reason = "stop"
    success_choice.message.refusal = None
    success_response = MagicMock(choices=[success_choice])

    # Fails once with 503, succeeds on retry
    mock_openai.chat.completions.create.side_effect = [error_503, success_response]

    with patch("time.sleep") as mock_sleep:
        res = client.investigate(
            intent="improvement",
            issue_description="audit",
            project_profile={},
            code_context="pass"
        )
        assert mock_sleep.called
        assert mock_openai.chat.completions.create.call_count == 2
        assert res["summary"] == "OK"

def test_transient_retry_exhausted():
    """Verify persistent transient error stops retrying after 1 retry (2 attempts total)."""
    client = NebiusClient(api_key="dummy_real_key")
    mock_openai = MagicMock()
    client.client = mock_openai

    req = httpx.Request("POST", "https://api.studio.nebius.ai/v1/chat/completions")
    resp_503 = httpx.Response(503, request=req)
    error_503 = APIStatusError(message="Service Unavailable", response=resp_503, body=None)

    mock_openai.chat.completions.create.side_effect = [error_503, error_503]

    with patch("time.sleep"):
        with pytest.raises(NebiusInferenceError) as exc_info:
            client.investigate(
                intent="improvement",
                issue_description="audit",
                project_profile={},
                code_context="pass"
            )
        assert mock_openai.chat.completions.create.call_count == 2
        assert "503" in str(exc_info.value)

def test_nemotron_disables_thinking_extra_body():
    """Verify nvidia/Nemotron-3_5-Lightning configures chat_template_kwargs: enable_thinking=False."""
    nemotron_client = NebiusClient(api_key="dummy_key", model_name="nvidia/Nemotron-3_5-Lightning")
    extra_kwargs = nemotron_client._get_model_extra_kwargs()
    assert extra_kwargs == {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}

    other_client = NebiusClient(api_key="dummy_key", model_name="meta-llama/Llama-3-70b")
    assert other_client._get_model_extra_kwargs() == {}

def test_investigate_fallback_to_reasoning():
    """Verify findings are parsed from reasoning if content is empty."""
    client = NebiusClient(api_key="dummy_real_key")
    mock_openai = MagicMock()
    client.client = mock_openai

    mock_choice = MagicMock()
    mock_choice.message.content = ""
    mock_choice.message.reasoning = json.dumps({
        "summary": "Recovered from reasoning",
        "findings": [{"id": "finding-1", "title": "Reasoning Finding"}]
    })
    mock_choice.finish_reason = "stop"
    mock_choice.message.refusal = None
    mock_openai.chat.completions.create.return_value = MagicMock(choices=[mock_choice])

    res = client.investigate(
        intent="improvement",
        issue_description="audit",
        project_profile={},
        code_context="pass"
    )
    assert res["summary"] == "Recovered from reasoning"
    assert len(res["findings"]) == 1
    assert res["findings"][0]["title"] == "Reasoning Finding"

def test_empty_response_raises_error():
    """Verify empty response without content or reasoning raises NebiusInferenceError."""
    client = NebiusClient(api_key="dummy_real_key")
    mock_openai = MagicMock()
    client.client = mock_openai

    mock_choice = MagicMock()
    mock_choice.message.content = ""
    mock_choice.message.reasoning = ""
    mock_choice.finish_reason = "stop"
    mock_choice.message.refusal = None
    mock_openai.chat.completions.create.return_value = MagicMock(choices=[mock_choice])

    with pytest.raises(NebiusInferenceError) as exc_info:
        client.investigate(
            intent="improvement",
            issue_description="audit",
            project_profile={},
            code_context="pass"
        )
    assert "empty response" in str(exc_info.value).lower()


