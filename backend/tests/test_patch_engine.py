import pytest
import os
import tempfile
from backend.app.patch_engine import PatchEngine

def test_apply_valid_patch():
    with tempfile.TemporaryDirectory() as temp_repo:
        os.system(f"cd {temp_repo} && git init && git config user.email 'test@test.com' && git config user.name 'Test' && echo 'old line' > file.txt && git add file.txt && git commit -m 'Initial'")
        
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

def test_fuzzy_apply_patch_preserves_nested_indentation_and_strips_json_artifacts():
    with tempfile.TemporaryDirectory() as temp_repo:
        os.system(f"cd {temp_repo} && git init && git config user.email 'test@test.com' && git config user.name 'Test'")
        
        sample_code = """def resolve_token(user):
    if user:
        return user.token

    return None
"""
        with open(os.path.join(temp_repo, "service.py"), "w") as f:
            f.write(sample_code)
            
        os.system(f"cd {temp_repo} && git add service.py && git commit -m 'Initial'")

        # Simulated patch with nested block (if not user: return None) and leaked trailing "}, from JSON
        nested_patch_with_json_leak = """--- a/service.py
+++ b/service.py
@@ -1,5 +1,6 @@
 def resolve_token(user):
-    if user:
-        return user.token
+    if not user:
+        raise ValueError("Missing")"},
+    return user.token
"""
        success = PatchEngine.apply_patch(temp_repo, nested_patch_with_json_leak)
        assert success is True

        with open(os.path.join(temp_repo, "service.py"), "r") as f:
            content = f.read()

        # Must compile without SyntaxError or IndentationError
        compile(content, "service.py", "exec")
        assert 'raise ValueError("Missing")' in content
        assert '"},' not in content

def test_patch_engine_preserves_dict_and_string_literals():
    """Verify that trailing braces and string quotes in valid Python code are never stripped."""
    with tempfile.TemporaryDirectory() as temp_repo:
        os.system(f"cd {temp_repo} && git init && git config user.email 'test@test.com' && git config user.name 'Test'")

        sample_code = """def parse_response(candidate, user):
    if not candidate:
        return None
    return candidate
"""
        with open(os.path.join(temp_repo, "client.py"), "w") as f:
            f.write(sample_code)

        os.system(f"cd {temp_repo} && git add client.py && git commit -m 'Initial'")

        # Patch adding dict literal ending in } and f-string ending in "
        patch = """--- a/client.py
+++ b/client.py
@@ -1,4 +1,6 @@
 def parse_response(candidate, user):
     if not candidate:
+        detail=f"Failed to decrypt stored token for user {user.id}: {e}"
+        return {"_raw": candidate}
-    return candidate
+    return {"data": candidate}
"""
        success = PatchEngine.apply_patch(temp_repo, patch)
        assert success is True

        with open(os.path.join(temp_repo, "client.py"), "r") as f:
            content = f.read()

        compile(content, "client.py", "exec")
        assert 'return {"_raw": candidate}' in content
        assert 'detail=f"Failed to decrypt stored token for user {user.id}: {e}"' in content
        assert 'return {"data": candidate}' in content

def test_patch_engine_target_file_hint_without_diff_headers():
    """Verify that patches missing diff headers apply when target_file_hint is provided."""
    with tempfile.TemporaryDirectory() as temp_repo:
        os.system(f"cd {temp_repo} && git init && git config user.email 'test@test.com' && git config user.name 'Test'")

        sample_code = """def add(a, b):
    return a - b
"""
        with open(os.path.join(temp_repo, "calc.py"), "w") as f:
            f.write(sample_code)

        os.system(f"cd {temp_repo} && git add calc.py && git commit -m 'Initial'")

        # Patch without --- a/ and +++ b/ headers
        headerless_patch = """@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
"""
        success = PatchEngine.apply_patch(temp_repo, headerless_patch, target_file_hint="calc.py")
        assert success is True

        with open(os.path.join(temp_repo, "calc.py"), "r") as f:
            content = f.read()

        assert "return a + b" in content

def test_fuzzy_apply_patch_does_not_corrupt_surrounding_indentation():
    """Verify that pure addition in nested blocks preserves original indentation of surrounding lines."""
    with tempfile.TemporaryDirectory() as temp_repo:
        os.system(f"cd {temp_repo} && git init && git config user.email 'test@test.com' && git config user.name 'Test'")

        sample_code = """def exchange_oauth_code(code: str, redirect_uri: str = None):
    payload = {
        "client_id": "123",
        "client_secret": "sec",
        "code": code,
    }
    if redirect_uri:
        payload["redirect_uri"] = redirect_uri
    return payload
"""
        with open(os.path.join(temp_repo, "service.py"), "w") as f:
            f.write(sample_code)

        os.system(f"cd {temp_repo} && git add service.py && git commit -m 'Initial'")

        # Patch adding a timeout field inside the payload dict
        patch = """--- a/service.py
+++ b/service.py
@@ -3,3 +3,4 @@
         "client_id": "123",
         "client_secret": "sec",
         "code": code,
+        "timeout": 15,
     }
     if redirect_uri:
"""
        success = PatchEngine.apply_patch(temp_repo, patch)
        assert success is True

        with open(os.path.join(temp_repo, "service.py"), "r") as f:
            content = f.read()

        # Must compile without IndentationError or SyntaxError
        compile(content, "service.py", "exec")
        assert 'if redirect_uri:' in content
        assert '    if redirect_uri:' in content
        assert '"timeout": 15,' in content

def test_patch_engine_normalizes_repo_name_prefix():
    """Verify that patches with repository folder prefixes in headers are resolved to the workspace root."""
    with tempfile.TemporaryDirectory() as temp_repo:
        os.system(f"cd {temp_repo} && git init && git config user.email 'test@test.com' && git config user.name 'Test'")

        sample_code = "VAL = 1\n"
        with open(os.path.join(temp_repo, "config.py"), "w") as f:
            f.write(sample_code)

        os.system(f"cd {temp_repo} && git add config.py && git commit -m 'Initial'")

        patch = """--- a/my-repo-name/config.py
+++ b/my-repo-name/config.py
@@ -1,1 +1,1 @@
-VAL = 1
+VAL = 2
"""
        success = PatchEngine.apply_patch(temp_repo, patch)
        assert success is True

        with open(os.path.join(temp_repo, "config.py"), "r") as f:
            content = f.read()

        assert "VAL = 2" in content



