import os
import subprocess
from unidiff import PatchSet

class PatchEngine:
    @staticmethod
    def apply_patch(workspace_path: str, patch_content: str) -> bool:
        patch_file_path = os.path.join(workspace_path, "repair.patch")
        try:
            with open(patch_file_path, "w") as f:
                f.write(patch_content)
            
            try:
                patch_set = PatchSet(patch_content)
                for patched_file in patch_set:
                    target_path = os.path.normpath(patched_file.target_file)

                    # Prevent absolute paths or path traversal
                    if target_path.startswith("..") or target_path.startswith("/"):
                        raise ValueError(f"Invalid path in patch: {target_path}")

                    # Prevent changes outside workspace
                    abs_target = os.path.abspath(os.path.join(workspace_path, target_path))
                    if not abs_target.startswith(os.path.abspath(workspace_path)):
                        raise ValueError(f"Target path outside workspace: {target_path}")

                    # Prevent modifying binary files implicitly by checking path
                    if any(target_path.endswith(ext) for ext in ['.exe', '.dll', '.so', '.pyc', '.zip', '.tar.gz']):
                        raise ValueError(f"Patching binary files is not allowed: {target_path}")

            except Exception as e:
                print(f"Patch validation failed: {e}")
                return False

            result = subprocess.run(
                ["git", "apply", "repair.patch"],
                cwd=workspace_path,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                print(f"Failed to apply patch: {result.stderr}")
                return False
                
            return True
            
        except Exception as e:
            print(f"Error applying patch: {e}")
            return False
        finally:
            if os.path.exists(patch_file_path):
                os.remove(patch_file_path)

