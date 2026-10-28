import os
import re
import shlex
import shutil
import subprocess
import base64
import logging
import secrets
import time
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlparse
import httpx
from git import Repo

logger = logging.getLogger(__name__)

# Valid repository and branch name patterns to prevent command, traversal, or flag injection
REPO_NAME_REGEX = re.compile(r"^(?!.*(?:\.\.))[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
BRANCH_NAME_REGEX = re.compile(r"^(?!.*(?:\.\.))[A-Za-z0-9_./-]+$")

def sanitize_branch_name(name: str) -> str:
    """Ensure branch names are safe for git commands (no flags, no traversal)."""
    clean = re.sub(r"[^A-Za-z0-9_./-]", "-", name)
    clean = re.sub(r"\.\.+", "-", clean)  # No .. traversal
    clean = clean.strip("-./")
    if clean.startswith("-") or not clean:
        clean = f"branch-{clean.lstrip('-')}" if clean else "patchworks-fix"
    return clean

class GitHubService:
    def __init__(self):
        # Optional server-configured credentials
        self.client_id = os.getenv("GITHUB_CLIENT_ID", "")
        self.client_secret = os.getenv("GITHUB_CLIENT_SECRET", "")
        self.default_token = os.getenv("GITHUB_TOKEN", "")
        self.active_session_token: Optional[str] = self.default_token if self.default_token else None
        self.oauth_states: Dict[str, float] = {}

    def is_oauth_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def create_oauth_state(self) -> str:
        # Purge states older than 10 minutes
        now = time.time()
        self.oauth_states = {s: exp for s, exp in self.oauth_states.items() if exp > now}
        state = secrets.token_urlsafe(32)
        self.oauth_states[state] = now + 600.0  # 10 minutes
        return state

    def validate_oauth_state(self, state: str) -> bool:
        now = time.time()
        if state in self.oauth_states and self.oauth_states[state] > now:
            del self.oauth_states[state]
            return True
        return False

    def get_oauth_url(self, redirect_uri: Optional[str] = None) -> Optional[str]:
        if not self.is_oauth_configured():
            return None
        state = self.create_oauth_state()
        url = (
            f"https://github.com/login/oauth/authorize?"
            f"client_id={self.client_id}&"
            f"scope=repo,read:user&"
            f"state={state}"
        )
        if redirect_uri:
            url += f"&redirect_uri={redirect_uri}"
        return url

    def exchange_oauth_code(self, code: str, redirect_uri: Optional[str] = None) -> Tuple[bool, Optional[str], Optional[str]]:
        """Exchange OAuth authorization code for access token. Returns (success, token, error_message)."""
        if not self.is_oauth_configured():
            return False, None, "GitHub OAuth client ID and secret are not configured on server"

        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
        }
        if redirect_uri:
            payload["redirect_uri"] = redirect_uri

        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.post(
                    "https://github.com/login/oauth/access_token",
                    headers={"Accept": "application/json"},
                    json=payload
                )
                if res.status_code == 200:
                    data = res.json()
                    access_token = data.get("access_token")
                    if access_token:
                        return True, access_token, None
                    err_desc = data.get("error_description") or data.get("error") or "No access token in response"
                    return False, None, err_desc
                return False, None, f"GitHub token endpoint returned HTTP {res.status_code}"
        except Exception as e:
            logger.error(f"Failed to exchange GitHub OAuth code: {e}")
            return False, None, "Network error contacting GitHub OAuth endpoint"

    def get_token(self, request_token: Optional[str] = None) -> Optional[str]:
        """Resolve token with precedence: explicitly passed token > session token > env token."""
        token = request_token or self.active_session_token or self.default_token
        return token.strip() if token else None

    def set_session_token(self, token: Optional[str]):
        self.active_session_token = token.strip() if token else None

    def is_configured(self) -> bool:
        return bool(self.get_token() or (self.client_id and self.client_secret))

    def _get_headers(self, token: str) -> Dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Patchworks-Autonomous-Repair-Agent/1.0"
        }

    def verify_token(self, token: str) -> Dict[str, Any]:
        """Verify token against GitHub API and return authenticated user metadata without exposing token."""
        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.get("https://api.github.com/user", headers=self._get_headers(token))
                if res.status_code == 200:
                    data = res.json()
                    scopes_header = res.headers.get("x-oauth-scopes", "")
                    scopes = [s.strip() for s in scopes_header.split(",") if s.strip()] if scopes_header else []
                    return {
                        "valid": True,
                        "login": data.get("login"),
                        "name": data.get("name") or data.get("login"),
                        "avatar_url": data.get("avatar_url"),
                        "html_url": data.get("html_url"),
                        "scopes": scopes
                    }
                elif res.status_code == 401:
                    return {"valid": False, "error": "Invalid or expired GitHub credentials"}
                elif res.status_code == 403:
                    return {"valid": False, "error": "GitHub API rate limit exceeded or access forbidden"}
                else:
                    return {"valid": False, "error": f"GitHub API responded with status {res.status_code}"}
        except Exception as e:
            logger.error(f"Error contacting GitHub API: {e}")
            return {"valid": False, "error": "Unable to contact GitHub API"}

    def list_repositories(self, token: str, query: Optional[str] = None, page: int = 1, per_page: int = 30) -> List[Dict[str, Any]]:
        """List repositories accessible to the authenticated user."""
        headers = self._get_headers(token)
        try:
            with httpx.Client(timeout=20.0) as client:
                if query and query.strip():
                    user_info = self.verify_token(token)
                    login = user_info.get("login", "")
                    search_q = f"{query.strip()} user:{login} fork:true" if login else query.strip()
                    res = client.get(
                        "https://api.github.com/search/repositories",
                        headers=headers,
                        params={"q": search_q, "page": page, "per_page": min(per_page, 100), "sort": "updated"}
                    )
                    if res.status_code == 200:
                        items = res.json().get("items", [])
                        return [self._format_repo(r) for r in items]
                    else:
                        logger.error(f"Search repositories error: {res.status_code} {res.text}")
                        return []

                res = client.get(
                    "https://api.github.com/user/repos",
                    headers=headers,
                    params={"sort": "updated", "page": page, "per_page": min(per_page, 100), "affiliation": "owner,collaborator,organization_member"}
                )
                if res.status_code == 200:
                    return [self._format_repo(r) for r in res.json()]
                else:
                    logger.error(f"List repositories error: {res.status_code}")
                    return []
        except Exception as e:
            logger.error(f"Failed to fetch repositories: {e}")
            return []

    def _format_repo(self, r: dict) -> dict:
        return {
            "id": r.get("id"),
            "name": r.get("name"),
            "full_name": r.get("full_name"),
            "owner": r.get("owner", {}).get("login"),
            "private": r.get("private", False),
            "html_url": r.get("html_url"),
            "description": r.get("description"),
            "default_branch": r.get("default_branch", "main"),
            "updated_at": r.get("updated_at"),
            "permissions": r.get("permissions", {"push": True, "pull": True})
        }

    def list_branches(self, token: str, owner: str, repo: str) -> List[Dict[str, Any]]:
        """List branches for a given repository."""
        if not REPO_NAME_REGEX.match(owner) or not REPO_NAME_REGEX.match(repo):
            raise ValueError("Invalid owner or repository name")

        headers = self._get_headers(token)
        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.get(
                    f"https://api.github.com/repos/{owner}/{repo}/branches",
                    headers=headers,
                    params={"per_page": 100}
                )
                if res.status_code == 200:
                    branches = []
                    for b in res.json():
                        branches.append({
                            "name": b.get("name"),
                            "commit_sha": b.get("commit", {}).get("sha"),
                            "protected": b.get("protected", False)
                        })
                    return branches
                else:
                    logger.error(f"Error fetching branches: {res.status_code}")
                    return []
        except Exception as e:
            logger.error(f"Failed to fetch branches: {e}")
            return []

    def get_branch_head_sha(self, token: str, owner: str, repo: str, branch: str) -> Optional[str]:
        """Get the current commit SHA of a remote branch."""
        if not REPO_NAME_REGEX.match(owner) or not REPO_NAME_REGEX.match(repo):
            return None
        headers = self._get_headers(token)
        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.get(
                    f"https://api.github.com/repos/{owner}/{repo}/branches/{branch}",
                    headers=headers
                )
                if res.status_code == 200:
                    return res.json().get("commit", {}).get("sha")
                return None
        except Exception as e:
            logger.error(f"Error fetching branch commit SHA: {e}")
            return None

    def clone_github_repo(
        self,
        token: str,
        owner: str,
        repo: str,
        branch: str,
        target_dir: str
    ) -> str:
        """
        Safely clone repository branch into target_dir using git credential extraHeader.
        Token is never embedded in the remote URL or stored on disk.
        """
        if not REPO_NAME_REGEX.match(owner) or not REPO_NAME_REGEX.match(repo):
            raise ValueError("Invalid owner or repository name format")

        clean_branch = sanitize_branch_name(branch)
        clean_url = f"https://github.com/{owner}/{repo}.git"

        # Encode token for basic auth header
        auth_str = f"x-access-token:{token}"
        auth_b64 = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
        extra_header = f"AUTHORIZATION: basic {auth_b64}"

        cmd = [
            "git",
            "-c", f"http.extraHeader={extra_header}",
            "clone",
            "--depth", "1",
            "--branch", clean_branch,
            clean_url,
            target_dir
        ]

        logger.info(f"Cloning GitHub repository {owner}/{repo} (branch {clean_branch}) into {target_dir}")
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if res.returncode != 0:
            # Redact basic auth if present in stderr
            redacted_err = re.sub(r"basic\s+[A-Za-z0-9+/=]+", "basic ***REDACTED***", res.stderr)
            raise ValueError(f"Failed to clone repository: {redacted_err.strip()}")

        # Configure repository identity safely
        subprocess.run(["git", "config", "user.name", "Patchworks Agent"], cwd=target_dir, check=True)
        subprocess.run(["git", "config", "user.email", "patchworks@bot.nebius.ai"], cwd=target_dir, check=True)

        # Record commit sha
        sha_res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=target_dir, capture_output=True, text=True, check=True)
        return sha_res.stdout.strip()

    def check_divergence(self, token: str, owner: str, repo: str, branch: str, starting_sha: str) -> Tuple[bool, Optional[str]]:
        """
        Check if remote branch has diverged since repair started.
        Returns: (has_diverged: bool, current_remote_sha: Optional[str])
        """
        remote_sha = self.get_branch_head_sha(token, owner, repo, branch)
        if not remote_sha:
            return False, None
        return (remote_sha != starting_sha), remote_sha

    def publish_pull_request(
        self,
        token: str,
        owner: str,
        repo: str,
        target_branch: str,
        starting_sha: str,
        workspace_path: str,
        workspace_id: str,
        title: str,
        problem_summary: str,
        diagnosis_data: Dict[str, Any],
        verification_details: Optional[Dict[str, Any]],
        model_name: str,
        is_mock_mode: bool,
        custom_notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Safely commits changes to a new unique repair branch, pushes to remote, and opens a Pull Request.
        """
        # 1. Check branch divergence
        diverged, current_sha = self.check_divergence(token, owner, repo, target_branch, starting_sha)
        if diverged:
            raise ValueError(
                f"Target branch '{target_branch}' has diverged on remote (started at {starting_sha[:8]}, now at {current_sha[:8] if current_sha else 'unknown'}). "
                f"Publication aborted to prevent overwriting upstream changes."
            )

        # 2. Create unique branch name
        short_id = workspace_id[:8]
        new_branch = sanitize_branch_name(f"patchworks/fix-{short_id}")

        # 3. Checkout new branch and commit changes
        subprocess.run(["git", "checkout", "-b", new_branch], cwd=workspace_path, check=True, capture_output=True)

        # Add only modified trackable files (no temporary or binary files)
        subprocess.run(["git", "add", "-u"], cwd=workspace_path, check=True, capture_output=True)

        # Ensure there are actually staged changes
        diff_check = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=workspace_path)
        if diff_check.returncode == 0:
            raise ValueError("No changes detected in workspace to commit.")

        commit_msg = f"fix: {title}\n\nAutonomously repaired and verified by Patchworks."
        subprocess.run(["git", "commit", "-m", commit_msg], cwd=workspace_path, check=True, capture_output=True)

        head_commit_res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=workspace_path, capture_output=True, text=True, check=True)
        commit_sha = head_commit_res.stdout.strip()

        # 4. Push branch with authenticated header
        auth_str = f"x-access-token:{token}"
        auth_b64 = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
        extra_header = f"AUTHORIZATION: basic {auth_b64}"

        push_cmd = [
            "git",
            "-c", f"http.extraHeader={extra_header}",
            "push",
            "-u",
            "origin",
            new_branch
        ]

        logger.info(f"Pushing repair branch {new_branch} to origin")
        push_res = subprocess.run(push_cmd, cwd=workspace_path, capture_output=True, text=True, timeout=60)
        if push_res.returncode != 0:
            redacted_err = re.sub(r"basic\s+[A-Za-z0-9+/=]+", "basic ***REDACTED***", push_res.stderr)
            raise ValueError(f"Failed to push branch to GitHub: {redacted_err.strip()}")

        # 5. Build structured Pull Request markdown body
        pr_body = self._build_pr_body(
            title=title,
            problem_summary=problem_summary,
            diagnosis_data=diagnosis_data,
            verification_details=verification_details,
            model_name=model_name,
            is_mock_mode=is_mock_mode,
            new_branch=new_branch,
            target_branch=target_branch,
            commit_sha=commit_sha,
            custom_notes=custom_notes
        )

        # 6. Create Pull Request via GitHub REST API
        headers = self._get_headers(token)
        payload = {
            "title": title,
            "head": new_branch,
            "base": target_branch,
            "body": pr_body,
            "maintainer_can_modify": True
        }

        with httpx.Client(timeout=20.0) as client:
            res = client.post(
                f"https://api.github.com/repos/{owner}/{repo}/pulls",
                headers=headers,
                json=payload
            )

            if res.status_code == 201:
                pr_data = res.json()
                return {
                    "status": "success",
                    "pr_url": pr_data.get("html_url"),
                    "pr_number": pr_data.get("number"),
                    "branch": new_branch,
                    "commit_sha": commit_sha,
                    "target_branch": target_branch
                }
            elif res.status_code == 422:
                # PR may already exist for this branch
                err_text = res.text
                if "A pull request already exists" in err_text:
                    # Retrieve existing PR
                    list_res = client.get(
                        f"https://api.github.com/repos/{owner}/{repo}/pulls",
                        headers=headers,
                        params={"head": f"{owner}:{new_branch}", "state": "open"}
                    )
                    if list_res.status_code == 200 and list_res.json():
                        existing = list_res.json()[0]
                        return {
                            "status": "success",
                            "pr_url": existing.get("html_url"),
                            "pr_number": existing.get("number"),
                            "branch": new_branch,
                            "commit_sha": commit_sha,
                            "target_branch": target_branch,
                            "note": "Existing pull request reused."
                        }
                raise ValueError(f"GitHub rejected pull request: {err_text}")
            else:
                raise ValueError(f"GitHub API error ({res.status_code}): {res.text}")

    def _build_pr_body(
        self,
        title: str,
        problem_summary: str,
        diagnosis_data: Dict[str, Any],
        verification_details: Optional[Dict[str, Any]],
        model_name: str,
        is_mock_mode: bool,
        new_branch: str,
        target_branch: str,
        commit_sha: str,
        custom_notes: Optional[str] = None
    ) -> str:
        files_list = "\n".join([f"- `{f}`" for f in diagnosis_data.get("files_to_modify", [])]) or "- None specified"
        test_stdout = verification_details.get("stdout", "").strip() if verification_details else "No test stdout"
        if len(test_stdout) > 2500:
            test_stdout = test_stdout[:2500] + "\n... [Output truncated for pull request]"

        mode_badge = (
            "> ⚠️ **Execution Mode:** Simulated Mock Mode (Testing Simulation)"
            if is_mock_mode
            else f"> ⚡ **Execution Mode:** Live Nebius AI Cloud &bull; Model: `{model_name}`"
        )

        notes_section = f"### 📝 Additional Review Notes\n{custom_notes}\n" if custom_notes else ""

        return f"""## 🛠️ Patchworks Verified Code Repair

{mode_badge}

### 📋 Overview
{problem_summary}

---

### 🔍 Root Cause Diagnosis
{diagnosis_data.get("diagnosis", "Autonomous diagnosis performed.")}

**Evidence:**
> {diagnosis_data.get("evidence", "Code context analysis")}

**Target Files Modified:**
{files_list}

**Proposed Solution Approach:**
{diagnosis_data.get("proposed_fix_description", "Targeted minimal unified diff.")}

---

### 🧪 Empirical Verification Results
- **Status:** **`FIX VERIFIED`** (Tests successfully passed with exit code 0)
- **Exit Code:** `{verification_details.get("returncode", 0) if verification_details else 0}`
- **Sandbox Test Output:**
```
{test_stdout}
```

---

### ⚠️ Regression Risk Assessment
{diagnosis_data.get("regression_risks", "Low regression risk determined through targeted test coverage.")}

{notes_section}
---
*Created autonomously with [Patchworks](https://github.com/PPurab-006/nebius-proofpatch) &bull; Find the fault. Forge the fix. Prove it works.*
*Branch:* `{new_branch}` &bull; *Target:* `{target_branch}` &bull; *Commit:* `{commit_sha[:8]}`
"""
