import os
import shutil
import tempfile
import subprocess
from git import Repo
import logging
import shlex
from urllib.parse import urlparse
import ipaddress
import socket
import zipfile

logger = logging.getLogger(__name__)

def is_safe_url(url: str) -> bool:
    parsed = urlparse(url)

    if parsed.username or parsed.password:
        return False

    if parsed.scheme == 'file':
        return True # For benchmark fixtures

    if parsed.scheme not in ['http', 'https']:
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
        if str(ip) == '169.254.169.254':
            return False

    except Exception:
        return False # Fail safe

    return True

class WorkspaceManager:
    def __init__(self, base_dir=None):
        self.base_dir = base_dir or tempfile.gettempdir()
        self.workspaces = {}

    def create_workspace(self, repo_url: str) -> str:
        if not is_safe_url(repo_url):
            raise ValueError(f"Unsafe or unsupported URL: {repo_url}")
            
        workspace_id = os.urandom(8).hex()
        workspace_path = os.path.join(self.base_dir, f"proofpatch_ws_{workspace_id}")
        
        try:
            logger.info(f"Cloning {repo_url} into {workspace_path}")
            Repo.clone_from(repo_url, workspace_path, depth=1)
            self.workspaces[workspace_id] = workspace_path
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

    def run_tests(self, workspace_id: str, command: str) -> dict:
        workspace_path = self.get_workspace_path(workspace_id)
        
        # Security: Parse the command safely
        try:
            cmd_args = shlex.split(command)
        except ValueError as e:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Malformed command string: {e}",
                "returncode": -1
             }
             
        if not cmd_args:
             return {
                "success": False,
                "stdout": "",
                "stderr": "Empty command provided",
                "returncode": -1
             }

        # Enforce explicit allowlist of base commands (no shell injection)
        base_cmd = cmd_args[0]
        allowed_bases = ["pytest", "python", "python3"]
        if base_cmd not in allowed_bases:
             return {
                "success": False,
                "stdout": "",
                "stderr": f"Command '{base_cmd}' not allowed. Allowed bases: {', '.join(allowed_bases)}",
                "returncode": -1
             }

        # Prevent obvious subshell or chaining attempts passed as arguments even when shell=False
        for arg in cmd_args:
            if any(char in arg for char in [';', '|', '&', '`', '$']):
                 return {
                    "success": False,
                    "stdout": "",
                    "stderr": "Potentially unsafe characters in command arguments.",
                    "returncode": -1
                 }

        try:
            # We explicitly use shell=False and pass the array of arguments to prevent injection
            result = subprocess.run(
                cmd_args,
                cwd=workspace_path,
                shell=False,
                capture_output=True,
                text=True,
                timeout=30 # Enforce timeout
            )
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode
            }
        except subprocess.TimeoutExpired:
             return {
                "success": False,
                "stdout": "",
                "stderr": "Test execution timed out after 30 seconds",
                "returncode": -1
             }
        except Exception as e:
             return {
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
