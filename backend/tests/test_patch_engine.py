import pytest
import os
import tempfile
from backend.app.patch_engine import PatchEngine

def test_apply_valid_patch():
    with tempfile.TemporaryDirectory() as temp_repo:
        os.system(f"cd {temp_repo} && git init && echo 'old line' > file.txt && git add file.txt && git commit -m 'Initial'")
        
        patch_content = """--- a/file.txt
+++ b/file.txt
@@ -1,1 +1,1 @@
-old line
+new line
"""
        success = PatchEngine.apply_patch(temp_repo, patch_content)
        assert success is True
        
        with open(os.path.join(temp_repo, "file.txt"), "r") as f:
            content = f.read().strip()
        assert content == "new line"

def test_reject_path_traversal():
    with tempfile.TemporaryDirectory() as temp_repo:
        patch_content = """--- a/../etc/passwd
+++ b/../etc/passwd
@@ -1,1 +1,1 @@
-root
+hacker
"""
        success = PatchEngine.apply_patch(temp_repo, patch_content)
        assert success is False
