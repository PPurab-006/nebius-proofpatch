import os
import re
import json
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Standard directories and files to ignore during repository inspection
IGNORE_DIRS = {
    '.git', '__pycache__', 'node_modules', '.venv', 'venv', 'env',
    'dist', 'out', 'build', '.next', 'target', '.cache', '.pytest_cache',
    '.vscode', '.idea', '.tox', '.mypy_cache', 'coverage', '.turbo'
}

IGNORE_EXTS = {
    '.exe', '.dll', '.so', '.dylib', '.pyc', '.pyo', '.pyd',
    '.map', '.min.js', '.min.css', '.vsix', '.zip', '.tar', '.gz',
    '.png', '.jpg', '.jpeg', '.gif', '.ico', '.svg', '.webp', '.mp4',
    '.pdf', '.wasm', '.bin', '.dat', '.lock', '.class', '.jar'
}

SOURCE_EXTS = {
    '.py', '.js', '.jsx', '.ts', '.tsx', '.json', '.md', '.html',
    '.css', '.rs', '.go', '.java', '.c', '.cpp', '.h', '.hpp',
    '.sh', '.yaml', '.yml', '.toml', '.esy'
}

class ProjectProfile(dict):
    """Container for repository metadata supporting both attribute and dict-key access."""
    def __init__(self, data: Dict[str, Any]):
        super().__init__(data)
        self.workspace_path: str = data.get("workspace_path", "")
        self.languages: List[str] = data.get("languages", [])
        self.frameworks: List[str] = data.get("frameworks", [])
        self.manifests: List[str] = data.get("manifests", [])
        self.test_files: List[str] = data.get("test_files", [])
        self.test_command: str = data.get("test_command", "")
        self.detected_test_command: Optional[str] = data.get("test_command") or None
        self.readme_summary: str = data.get("readme_summary", "")
        self.directory_structure: List[str] = data.get("directory_structure", [])
        self.file_count: int = data.get("file_count", 0)
        self.source_files_count: int = data.get("file_count", 0)
        self.total_source_bytes: int = data.get("total_source_bytes", 0)
        self.core_files: List[str] = data.get("core_files", [])

    def to_dict(self) -> Dict[str, Any]:
        d = dict(self)
        d["detected_test_command"] = self.detected_test_command
        d["source_files_count"] = self.file_count
        return d

class RepoInspector:
    """Safely profiles repositories, locates manifests/tests, and prepares bounded inspection context."""

    @staticmethod
    def inspect(workspace_path: str, explicit_test_command: Optional[str] = None) -> ProjectProfile:
        real_ws_path = os.path.realpath(workspace_path)
        if not os.path.isdir(real_ws_path):
            raise ValueError(f"Workspace directory not found: {workspace_path}")

        profile: Dict[str, Any] = {
            "workspace_path": real_ws_path,
            "languages": [],
            "frameworks": [],
            "manifests": [],
            "test_files": [],
            "test_command": explicit_test_command or "",
            "readme_summary": "",
            "directory_structure": [],
            "file_count": 0,
            "total_source_bytes": 0,
            "core_files": []
        }

        lang_counts: Dict[str, int] = {}
        all_files: List[Tuple[str, int]] = []

        # 1. Walk workspace with bounded traversal
        max_traversal_files = 1000
        traversed = 0

        for root, dirs, files in os.walk(real_ws_path):
            # Prune ignored directories in-place
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith('.')]

            rel_root = os.path.relpath(root, real_ws_path)
            if rel_root != ".":
                profile["directory_structure"].append(rel_root)

            for file in files:
                traversed += 1
                if traversed > max_traversal_files:
                    break

                ext = os.path.splitext(file)[1].lower()
                if ext in IGNORE_EXTS or file.endswith("-lock.json"):
                    continue

                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, real_ws_path)

                # Prevent path traversal outside workspace
                real_file_path = os.path.realpath(full_path)
                if not (real_file_path == real_ws_path or real_file_path.startswith(real_ws_path + os.sep)):
                    continue

                try:
                    size = os.path.getsize(full_path)
                except OSError:
                    continue

                all_files.append((rel_path, size))
                profile["total_source_bytes"] += size

                # Language detection
                if ext == ".py":
                    lang_counts["Python"] = lang_counts.get("Python", 0) + size
                elif ext in [".ts", ".tsx"]:
                    lang_counts["TypeScript"] = lang_counts.get("TypeScript", 0) + size
                elif ext in [".js", ".jsx"]:
                    lang_counts["JavaScript"] = lang_counts.get("JavaScript", 0) + size
                elif ext == ".rs":
                    lang_counts["Rust"] = lang_counts.get("Rust", 0) + size
                elif ext == ".go":
                    lang_counts["Go"] = lang_counts.get("Go", 0) + size
                elif ext in [".esy"]:
                    lang_counts["EasyType"] = lang_counts.get("EasyType", 0) + size

                # Manifest detection
                if file in ["package.json", "pyproject.toml", "setup.py", "requirements.txt", "Cargo.toml", "go.mod", "tsconfig.json"]:
                    profile["manifests"].append(rel_path)

                # Test file detection
                lower_file = file.lower()
                if (lower_file.startswith("test_") or lower_file.endswith("_test.py") or
                    lower_file.endswith(".test.ts") or lower_file.endswith(".spec.ts") or
                    lower_file.endswith(".test.js") or lower_file.endswith(".spec.js") or
                    "/tests/" in f"/{rel_path}/" or "/test/" in f"/{rel_path}/"):
                    profile["test_files"].append(rel_path)

            if traversed > max_traversal_files:
                break

        profile["file_count"] = len(all_files)

        # Ranked languages
        profile["languages"] = [lang for lang, _ in sorted(lang_counts.items(), key=lambda x: x[1], reverse=True)]

        # 2. Extract README overview
        readme_candidates = ["README.md", "readme.md", "README.txt", "README"]
        for cand in readme_candidates:
            cand_path = os.path.join(real_ws_path, cand)
            if os.path.isfile(cand_path):
                try:
                    with open(cand_path, "r", encoding="utf-8", errors="ignore") as f:
                        text = f.read(2500)
                        # Extract first meaningful paragraphs
                        profile["readme_summary"] = text.strip()
                        break
                except Exception as e:
                    logger.debug(f"Could not read README: {e}")

        # 3. Detect framework and test command if not explicitly supplied
        if not profile["test_command"]:
            profile["test_command"] = RepoInspector._detect_test_command(real_ws_path, profile)

        # 4. Identify core files (manifests, main entrypoints, non-test files sorted by size/priority)
        core_files: List[str] = []
        for rel_path, _ in all_files:
            base = os.path.basename(rel_path)
            if base in profile["manifests"] or base in ["README.md", "easytype.py", "main.py", "app.py", "index.ts", "extension.ts"]:
                if rel_path not in core_files:
                    core_files.append(rel_path)

        # Fill up to 10 files
        for rel_path, _ in sorted(all_files, key=lambda x: x[1], reverse=True):
            if rel_path not in core_files and rel_path not in profile["test_files"]:
                core_files.append(rel_path)
            if len(core_files) >= 10:
                break

        profile["core_files"] = core_files
        return ProjectProfile(profile)

    @staticmethod
    def _detect_test_command(workspace_path: str, profile: Dict[str, Any]) -> str:
        """Infer safe test command based on manifests and language structure."""
        # 1. package.json check
        pkg_json_path = os.path.join(workspace_path, "package.json")
        if os.path.isfile(pkg_json_path):
            try:
                with open(pkg_json_path, "r", encoding="utf-8", errors="ignore") as f:
                    data = json.load(f)
                    scripts = data.get("scripts", {})
                    if "test" in scripts and scripts["test"] != "echo \"Error: no test specified\" && exit 1":
                        return "npm test"
            except Exception:
                pass

        # Check nested package.json (e.g. extension directory)
        for manifest in profile.get("manifests", []):
            if manifest.endswith("package.json"):
                pkg_path = os.path.join(workspace_path, manifest)
                try:
                    with open(pkg_path, "r", encoding="utf-8", errors="ignore") as f:
                        data = json.load(f)
                        scripts = data.get("scripts", {})
                        if "test" in scripts and "no test specified" not in scripts["test"]:
                            dir_name = os.path.dirname(manifest)
                            return f"cd {dir_name} && npm test" if dir_name else "npm test"
                except Exception:
                    pass

        # 2. Python test files check
        if "Python" in profile.get("languages", []) or any(f.endswith(".py") for f in profile.get("test_files", [])):
            if profile.get("test_files"):
                # If pytest files exist or simple tests
                return "pytest"
            return ""

        # 3. Rust check
        if "Rust" in profile.get("languages", []):
            return "cargo test"

        # 4. Go check
        if "Go" in profile.get("languages", []):
            return "go test ./..."

        return ""

    @staticmethod
    def build_bounded_context(workspace_path: str, profile: Optional[Dict[str, Any]] = None, max_total_chars: int = 24000) -> str:
        """Construct bounded, security-redacted code context for LLM investigation."""
        real_ws_path = os.path.realpath(workspace_path)
        if profile is None:
            profile = RepoInspector.inspect(real_ws_path)
        snippets: List[str] = []
        total_chars = 0

        # Prioritize core files + up to 2 test files
        target_files = list(profile.get("core_files", []))
        test_files = profile.get("test_files", [])[:2]
        for tf in test_files:
            if tf not in target_files:
                target_files.append(tf)

        for rel_path in target_files:
            full_path = os.path.join(real_ws_path, rel_path)
            if not os.path.isfile(full_path):
                continue

            try:
                if os.path.getsize(full_path) > 100 * 1024:
                    snippet = f"--- {rel_path} ---\n[File truncated: Too large]\n"
                    snippets.append(snippet)
                    total_chars += len(snippet)
                    continue

                # Per-file cap to prevent single-file domination
                file_cap = 4000
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read(file_cap + 500)
                    if len(content) > file_cap:
                        content = content[:file_cap] + "\n... [File truncated for inspection budget]"

                snippet = f"--- {rel_path} ---\n<untrusted_source_code>\n{content}\n</untrusted_source_code>\n"
                if total_chars + len(snippet) > max_total_chars:
                    remaining = max_total_chars - total_chars
                    if remaining > 300:
                        snippets.append(snippet[:remaining] + "\n... [Context limit reached]\n")
                    break

                snippets.append(snippet)
                total_chars += len(snippet)
            except Exception as e:
                logger.debug(f"Could not read file {rel_path}: {e}")

        return "\n".join(snippets)
