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

def test_fuzzy_apply_patch_with_stripped_indentation():
    with tempfile.TemporaryDirectory() as temp_repo:
        os.system(f"cd {temp_repo} && git init && git config user.email 'test@test.com' && git config user.name 'Test'")
        
        sample_code = """def authenticate(user):
    if user:
        # Authenticated branch
        return check_session()

    # Fallback to guest
    return guest_token()
"""
        with open(os.path.join(temp_repo, "auth.py"), "w") as f:
            f.write(sample_code)
            
        os.system(f"cd {temp_repo} && git add auth.py && git commit -m 'Initial'")

        # Simulated LLM output: dropped leading spaces and approximate hunk offset (@@ -50,4 +50,3 @@)
        bad_llm_patch = """--- a/auth.py
+++ b/auth.py
@@ -50,4 +50,3 @@ def authenticate
 if user:
  # Authenticated branch
  return check_session()
- # Fallback to guest
- return guest_token()
+ return None
"""
        success = PatchEngine.apply_patch(temp_repo, bad_llm_patch)
        assert success is True

        with open(os.path.join(temp_repo, "auth.py"), "r") as f:
            content = f.read()

        assert "guest_token()" not in content
        assert "        return None" in content or "    return None" in content

