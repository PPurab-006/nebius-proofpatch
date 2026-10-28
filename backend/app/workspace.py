import os
import sys
import shutil
import tempfile
import subprocess
from typing import Optional, Dict, Any
from git import Repo
import logging
import shlex
from urllib.parse import urlparse
import ipaddress
import socket
import zipfile
import re

logger = logging.getLogger(__name__)

def get_benchmark_fixtures_dir() -> str:
    """Resolve the directory containing benchmark fixtures reliably across environments."""
    # 1. Environment variable override
    env_dir = os.environ.get("BENCHMARK_FIXTURES_DIR")
    if env_dir and os.path.isdir(env_dir):
        return os.path.abspath(env_dir)

    # 2. Project-relative path from workspace.py (backend/app/workspace.py -> ../../benchmark_fixtures)
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    project_relative = os.path.abspath(os.path.join(current_file_dir, "..", "..", "benchmark_fixtures"))
    if os.path.isdir(project_relative):
        return project_relative

    # 3. Current working directory fallback
    cwd_relative = os.path.abspath(os.path.join(os.getcwd(), "benchmark_fixtures"))
    if os.path.isdir(cwd_relative):
        return cwd_relative

    # 4. Container fallback (/app/benchmark_fixtures)
    if os.path.isdir("/app/benchmark_fixtures"):
        return "/app/benchmark_fixtures"

    return project_relative

def resolve_benchmark_fixture_name(target: Optional[str]) -> Optional[str]:
    """
    Resolve whether a given input or URL targets a built-in benchmark fixture.
    Supports formats:
      - 'benchmark://simple_bug' or 'benchmark://edge_case'
      - 'benchmark:simple_bug' or 'benchmark:edge_case'
      - 'file:///app/benchmark_fixtures/edge_case' or 'file://.../benchmark_fixtures/<name>'
      - '/app/benchmark_fixtures/<name>' or '.../benchmark_fixtures/<name>'
      - Bare names: 'simple_bug', 'edge_case'
    Returns the sanitized fixture name if it exists in the resolved benchmark fixtures directory,
    or None otherwise.
    """
    if not target or not isinstance(target, str):
        return None

    trimmed = target.strip()
    if not trimmed:
        return None

    candidate_name = None

    parsed = urlparse(trimmed)
    if parsed.scheme == "benchmark":
        candidate_name = parsed.netloc or parsed.path.strip("/")
    elif trimmed.startswith("benchmark:"):
        candidate_name = trimmed[len("benchmark:"):].strip("/")
    elif "/benchmark_fixtures/" in trimmed:
        candidate_name = trimmed.split("/benchmark_fixtures/")[-1].strip("/")
    elif trimmed in ["simple_bug", "edge_case"]:
        candidate_name = trimmed

    if not candidate_name:
        return None

    # Strip any trailing .git or slashes
    if candidate_name.endswith(".git"):
        candidate_name = candidate_name[:-4]
    candidate_name = candidate_name.strip("/")

    # Strict alphanumeric + hyphen + underscore check (prevents path traversal)
    if not re.match(r"^[a-zA-Z0-9_\-]+$", candidate_name):
        return None

    fixtures_dir = get_benchmark_fixtures_dir()
    real_fixtures_dir = os.path.realpath(fixtures_dir)
    target_fixture_dir = os.path.realpath(os.path.join(fixtures_dir, candidate_name))

    # Verify containment within fixtures directory and ensure directory exists
    if not target_fixture_dir.startswith(real_fixtures_dir + os.sep):
        return None

    if not os.path.isdir(target_fixture_dir):
        return None

    return candidate_name

def is_safe_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False

    parsed = urlparse(url.strip())

    if parsed.username or parsed.password:
        return False

    # Allow custom benchmark scheme with strict fixture name formatting
    if parsed.scheme == "benchmark":
        fixture_name = parsed.netloc or parsed.path.strip("/")
        return bool(re.match(r"^[a-zA-Z0-9_\-]+$", fixture_name))

    # For file:// URLs: prevent arbitrary local path traversal.
    # Allow only file URLs strictly pointing to temp dir (used in tests) or benchmark fixtures dir.
    if parsed.scheme == "file":
        if ".." in parsed.path:
            return False
        clean_path = os.path.abspath(parsed.path)
        temp_dir = os.path.abspath(tempfile.gettempdir())
        fixtures_dir = os.path.abspath(get_benchmark_fixtures_dir())
        in_temp = (clean_path == temp_dir) or clean_path.startswith(temp_dir + os.sep) or clean_path.startswith("/tmp")
        in_fixtures = (clean_path == fixtures_dir) or clean_path.startswith(fixtures_dir + os.sep)
        return in_temp or in_fixtures

    # Support owner/repo shorthand for GitHub (e.g. PPurab-006/EasyType)
    trimmed = url.strip()
    if re.match(r"^[a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-]+(?:\.git)?$", trimmed):
        return True

    if parsed.scheme not in ["http", "https"]:
        return False

    try:
        hostname = parsed.hostname
        if not hostname:
            return False

        # Resolve hostname
        ip_addr = socket.gethostbyname(hostname)
        ip = ipaddress.ip_address(ip_addr)

        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return False

        # Check cloud metadata
        if str(ip) == "169.254.169.254":
            return False

    except Exception:
        return False  # Fail safe

    return True

class WorkspaceManager:
    def __init__(self, base_dir=None):
        self.base_dir = base_dir or tempfile.gettempdir()
        self.workspaces = {}
        self.workspace_metadata = {}

    def create_workspace_from_benchmark(self, fixture_name: str) -> str:
        """Create an isolated workspace initialized from a built-in benchmark fixture."""
        fixtures_dir = get_benchmark_fixtures_dir()

        # Security: validate fixture_name format (no path traversal)
        if not fixture_name or not re.match(r"^[a-zA-Z0-9_\-]+$", fixture_name):
            raise ValueError(f"Invalid benchmark fixture identifier: '{fixture_name}'")

        real_fixtures_dir = os.path.realpath(fixtures_dir)
        src_path = os.path.abspath(os.path.join(fixtures_dir, fixture_name))
        real_src_path = os.path.realpath(src_path)

        # Ensure it is strictly inside fixtures_dir
        if not (real_src_path == real_fixtures_dir or real_src_path.startswith(real_fixtures_dir + os.sep)):
            raise ValueError(f"Benchmark fixture traversal detected: '{fixture_name}'")

        if not os.path.isdir(real_src_path):
            raise ValueError(f"Benchmark fixture '{fixture_name}' not found at {src_path}")

        workspace_id = os.urandom(8).hex()
        workspace_path = os.path.join(self.base_dir, f"proofpatch_ws_{workspace_id}")

        try:
            logger.info(f"Initializing benchmark workspace '{fixture_name}' at {workspace_path}")

            # Copy all files from fixture, excluding .git, __pycache__, .pytest_cache
            def ignore_patterns(path, names):
                ignored = set()
                for name in names:
                    if name in (".git", "__pycache__", ".pytest_cache", ".tox", ".venv", "venv"):
                        ignored.add(name)
                    elif name.endswith(".pyc") or name.endswith(".pyo"):
                        ignored.add(name)
                return ignored

            shutil.copytree(real_src_path, workspace_path, ignore=ignore_patterns)

            # Initialize a fresh Git repository in the isolated workspace
            repo = Repo.init(workspace_path)
            with repo.config_writer() as cw:
                cw.set_value("user", "name", "Patchworks Benchmark")
                cw.set_value("user", "email", "benchmark@patchworks.test")

            repo.git.add(A=True)
            repo.index.commit(f"Initial commit for benchmark fixture: {fixture_name}")

            head_sha = repo.head.commit.hexsha

            self.workspaces[workspace_id] = workspace_path
            self.workspace_metadata[workspace_id] = {
                "source_type": "benchmark",
                "benchmark_name": fixture_name,
                "target_branch": "main",
                "starting_commit_sha": head_sha
            }
            return workspace_id
        except Exception as e:
            logger.error(f"Failed to create benchmark workspace: {e}")
            if os.path.exists(workspace_path):
                shutil.rmtree(workspace_path)
            raise ValueError(f"Could not initialize benchmark workspace: {str(e)}")

    def create_workspace(self, repo_url: str, branch: Optional[str] = None) -> str:
        # Check if repo_url represents a built-in benchmark fixture
        benchmark_name = resolve_benchmark_fixture_name(repo_url)
        if benchmark_name:
            return self.create_workspace_from_benchmark(benchmark_name)

        trimmed = repo_url.strip()
        if re.match(r"^[a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-]+(?:\.git)?$", trimmed):
            repo_url = f"https://github.com/{trimmed}"

        if not is_safe_url(repo_url):
            raise ValueError(f"Unsafe or unsupported URL: {repo_url}")

        workspace_id = os.urandom(8).hex()
        workspace_path = os.path.join(self.base_dir, f"proofpatch_ws_{workspace_id}")

        try:
            logger.info(f"Cloning {repo_url} into {workspace_path}")
            clone_kwargs = {"depth": 1}
            if branch:
                clone_kwargs["branch"] = branch
            Repo.clone_from(repo_url, workspace_path, **clone_kwargs)
            self.workspaces[workspace_id] = workspace_path

            # Record starting commit SHA and initial metadata
            try:
                head_sha = Repo(workspace_path).head.commit.hexsha
            except Exception:
                head_sha = "unknown"

            self.workspace_metadata[workspace_id] = {
                "source_type": "git",
                "repo_url": repo_url,
                "target_branch": branch or "main",
                "starting_commit_sha": head_sha
            }
            return workspace_id
        except Exception as e:
            logger.error(f"Failed to clone repository: {e}")
            if os.path.exists(workspace_path):
                shutil.rmtree(workspace_path)
            raise ValueError(f"Could not clone repository: {str(e)}")

    def create_workspace_from_zip(self, zip_path: str) -> str:
        workspace_id = os.urandom(8).hex()
        workspace_path = os.path.join(self.base_dir, f"proofpatch_ws_{workspace_id}")
        os.makedirs(workspace_path, exist_ok=True)

        MAX_SIZE = 50 * 1024 * 1024 # 50MB
        MAX_FILES = 500

        try:
            total_size = 0
            file_count = 0
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                for member in zip_ref.infolist():
                    if member.is_dir():
                        continue

                    target_path = os.path.abspath(os.path.join(workspace_path, member.filename))
                    if not target_path.startswith(os.path.abspath(workspace_path)):
                        raise ValueError("Zip Slip vulnerability detected")

                    total_size += member.file_size
                    file_count += 1

                    if total_size > MAX_SIZE:
                        raise ValueError("Archive exceeds maximum allowed size (50MB)")
                    if file_count > MAX_FILES:
                        raise ValueError("Archive exceeds maximum allowed files (500)")

                zip_ref.extractall(workspace_path)

            # Initialize git repo to allow patching
            repo = Repo.init(workspace_path)
            with repo.config_writer() as cw:
                cw.set_value("user", "name", "ProofPatch")
                cw.set_value("user", "email", "bot@proofpatch.test")
            repo.git.add(A=True)
            repo.index.commit("Initial commit from ZIP upload")

            self.workspaces[workspace_id] = workspace_path
            return workspace_id
        except Exception as e:
            if os.path.exists(workspace_path):
                shutil.rmtree(workspace_path)
            raise ValueError(f"Failed to process ZIP upload: {str(e)}")

    def get_workspace_path(self, workspace_id: str) -> str:
        if workspace_id not in self.workspaces:
            raise ValueError(f"Workspace {workspace_id} not found")
        return self.workspaces[workspace_id]

    def register_workspace(self, workspace_id: str, workspace_path: str, metadata: Dict[str, Any]):
        """Register an externally created workspace (e.g. from GitHub clone) with metadata."""
        self.workspaces[workspace_id] = workspace_path
        self.workspace_metadata[workspace_id] = metadata

    def get_workspace_metadata(self, workspace_id: str) -> Dict[str, Any]:
        return self.workspace_metadata.get(workspace_id, {})

    def update_workspace_metadata(self, workspace_id: str, updates: Dict[str, Any]):
        if workspace_id not in self.workspace_metadata:
            self.workspace_metadata[workspace_id] = {}
        self.workspace_metadata[workspace_id].update(updates)

    def cleanup_workspace(self, workspace_id: str):
        if workspace_id in self.workspaces:
            path = self.workspaces[workspace_id]
            try:
                shutil.rmtree(path)
                logger.info(f"Cleaned up workspace {workspace_id} at {path}")
            except Exception as e:
                logger.error(f"Failed to cleanup workspace {workspace_id}: {e}")
            finally:
                del self.workspaces[workspace_id]
                self.workspace_metadata.pop(workspace_id, None)

    def run_tests(self, workspace_id: str, command: str) -> dict:
        workspace_path = self.get_workspace_path(workspace_id)
        
        # Security: Parse the command safely
        try:
            cmd_args = shlex.split(command)
        except ValueError as e:
            return {
                "command": command,
                "success": False,
                "stdout": "",
                "stderr": f"Malformed command string: {e}",
                "returncode": -1
             }
             
        if not cmd_args:
             return {
                "command": command,
                "success": False,
                "stdout": "",
                "stderr": "Empty command provided",
                "returncode": -1
             }

        # Enforce explicit allowlist of base commands (no shell injection)
        base_cmd = cmd_args[0]
        allowed_bases = ["pytest", "python", "python3", "npm", "node", "cargo", "go"]
        if base_cmd not in allowed_bases:
             return {
                "command": command,
                "success": False,
                "stdout": "",
                "stderr": f"Command '{base_cmd}' not allowed. Allowed bases: {', '.join(allowed_bases)}",
                "returncode": -1
             }

        # Prevent obvious subshell or chaining attempts passed as arguments even when shell=False
        for arg in cmd_args:
            if any(char in arg for char in [';', '|', '&', '`', '$']):
                 return {
                    "command": command,
                    "success": False,
                    "stdout": "",
                    "stderr": "Potentially unsafe characters in command arguments.",
                    "returncode": -1
                 }

        # Resolve command to deterministic environment
        exec_args = list(cmd_args)
        if base_cmd in ["python", "python3"]:
            exec_args[0] = sys.executable
        elif base_cmd == "pytest":
            try:
                import pytest  # noqa: F401
                # Disable conflicting external plugins, ignore benchmark fixtures with intentional defects, and suppress warning clutter
                exec_args = [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-p",
                    "no:launch_testing",
                    "--disable-warnings",
                    "--ignore=benchmark_fixtures"
                ] + list(cmd_args[1:])
            except ImportError:
                return {
                    "command": command,
                    "success": False,
                    "stdout": "",
                    "stderr": f"pytest is not installed in the active environment ({sys.executable}).",
                    "returncode": -1
                }
        elif base_cmd in ["npm", "node", "cargo", "go"]:
            resolved_bin = shutil.which(base_cmd)
            if not resolved_bin:
                return {
                    "command": command,
                    "success": False,
                    "stdout": "",
                    "stderr": f"Command binary '{base_cmd}' is not installed or available on PATH in the sandbox environment.",
                    "returncode": -1
                }
            exec_args[0] = resolved_bin

        # Construct isolated environment:
        # Prepend active interpreter bin to PATH and isolate PYTHONPATH strictly to the workspace
        env = os.environ.copy()
        venv_bin = os.path.dirname(sys.executable)
        env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"
        env["PYTHONPATH"] = workspace_path
        env["PYTHONNOUSERSITE"] = "1"

        test_timeout = int(os.getenv("TEST_TIMEOUT", "120"))
        try:
            # We explicitly use shell=False and pass the array of arguments to prevent injection
            result = subprocess.run(
                exec_args,
                cwd=workspace_path,
                env=env,
                shell=False,
                capture_output=True,
                text=True,
                timeout=test_timeout
            )
            return {
                "command": command,
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode
            }
        except subprocess.TimeoutExpired as te:
             partial_out = te.stdout.decode("utf-8", errors="ignore") if isinstance(te.stdout, bytes) else (te.stdout or "")
             partial_err = te.stderr.decode("utf-8", errors="ignore") if isinstance(te.stderr, bytes) else (te.stderr or "")
             return {
                "command": command,
                "success": False,
                "stdout": partial_out,
                "stderr": f"Test execution timed out after {test_timeout} seconds\n{partial_err}".strip(),
                "returncode": -1
             }
        except Exception as e:
             return {
                "command": command,
                "success": False,
                "stdout": "",
                "stderr": f"Error running tests: {str(e)}",
                "returncode": -1
             }

    def rollback_patch(self, workspace_id: str) -> bool:
        workspace_path = self.get_workspace_path(workspace_id)
        try:
            subprocess.run(
                ["git", "reset", "--hard", "HEAD"],
                cwd=workspace_path,
                check=True,
                capture_output=True
            )
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Rollback failed: {e.stderr}")
            return False
