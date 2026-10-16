import os
import subprocess
from unidiff import PatchSet

class PatchEngine:
    @staticmethod
    def apply_patch(workspace_path: str, patch_content: str) -> bool:
        # Write patch to a temporary file
        patch_file_path = os.path.join(workspace_path, "repair.patch")
        try:
            with open(patch_file_path, "w") as f:
                f.write(patch_content)
            
            # Validate patch content (preventing path traversal like ../)
            try:
                patch_set = PatchSet(patch_content)
                for patched_file in patch_set:
                    target_path = os.path.normpath(patched_file.target_file)
                    if target_path.startswith("..") or target_path.startswith("/"):
                        raise ValueError(f"Invalid path in patch: {target_path}")
            except Exception as e:
                print(f"Patch validation failed: {e}")
                return False

            # Apply patch using git apply
            # we use git apply instead of standard patch to handle renames/adds better and ensure it's tracked
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

