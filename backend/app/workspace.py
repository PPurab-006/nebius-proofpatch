import os
import shutil
import tempfile
import subprocess
from git import Repo
import logging
import shlex
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

class WorkspaceManager:
    def __init__(self, base_dir=None):
        self.base_dir = base_dir or tempfile.gettempdir()
        self.workspaces = {}

    def create_workspace(self, repo_url: str) -> str:
        # Validate URL to prevent SSRF and arbitrary local file access
        parsed_url = urlparse(repo_url)
        allowed_schemes = ['http', 'https']
        # For the sake of the local hackathon demo/benchmarking, we allow 'file' temporarily
        # but in a real prod scenario, we'd restrict it to git/http(s).
        if parsed_url.scheme not in allowed_schemes and parsed_url.scheme != 'file':
            raise ValueError(f"Unsupported URL scheme: {parsed_url.scheme}")
            
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
