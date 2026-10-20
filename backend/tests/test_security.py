import pytest
from backend.app.workspace import WorkspaceManager, is_safe_url
from backend.app.patch_engine import PatchEngine
import tempfile
import zipfile
import os

def test_url_validation():
    # Safe URLs
    assert is_safe_url("https://github.com/user/repo") == True
    assert is_safe_url("http://example.com/repo.git") == True
    assert is_safe_url("file:///tmp/repo") == True

    # Unsafe URLs
    assert is_safe_url("http://127.0.0.1/repo") == False
    assert is_safe_url("http://169.254.169.254/latest/meta-data") == False
    assert is_safe_url("https://user:pass@github.com/repo") == False
    assert is_safe_url("ftp://example.com/repo") == False

def test_zip_slip_prevention():
    wm = WorkspaceManager()

    # Create malicious zip
    with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as f:
        zip_path = f.name

    try:
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr("../../../etc/passwd", "malicious content")

        with pytest.raises(ValueError, match="Zip Slip"):
            wm.create_workspace_from_zip(zip_path)
    finally:
        os.remove(zip_path)

def test_command_injection_prevention():
    wm = WorkspaceManager()

    # We must mock get_workspace_path so run_tests doesn't fail on "dummy"
    original_get_workspace_path = wm.get_workspace_path
    wm.get_workspace_path = lambda x: "/tmp"

    try:
        # Empty command
        res = wm.run_tests("dummy", "")
        assert res["success"] == False

        # Disallowed base command
        res = wm.run_tests("dummy", "ls -la")
        assert res["success"] == False
        assert "not allowed" in res["stderr"]

        # Injection attempt in args
        res = wm.run_tests("dummy", "pytest test.py; rm -rf /")
        assert res["success"] == False
        assert "unsafe characters" in res["stderr"]

        res = wm.run_tests("dummy", "pytest `echo test`")
        assert res["success"] == False
        assert "unsafe characters" in res["stderr"]
    finally:
        wm.get_workspace_path = original_get_workspace_path

def test_path_traversal_in_patch():
    # Absolute path
    malicious_patch_1 = """
--- a/file.py
+++ /etc/passwd
@@ -1,1 +1,1 @@
-old
+new
"""
    assert PatchEngine.apply_patch("/tmp", malicious_patch_1) == False

    # Traversal
    malicious_patch_2 = """
--- a/file.py
+++ b/../../passwd
@@ -1,1 +1,1 @@
-old
+new
"""
    assert PatchEngine.apply_patch("/tmp", malicious_patch_2) == False

    # Binary
    malicious_patch_3 = """
--- a/file.py
+++ b/file.exe
@@ -1,1 +1,1 @@
-old
+new
"""
    assert PatchEngine.apply_patch("/tmp", malicious_patch_3) == False
