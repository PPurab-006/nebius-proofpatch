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
    '.pdf', '.wasm', '.bin', '.dat', '.lock', '.class', '.jar',
    '.tmLanguage', '.sublime-syntax', '.tmTheme'
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
                if (ext in IGNORE_EXTS or file.endswith("-lock.json") or 
                    file.endswith(".lock") or file.endswith(".tmLanguage.json")):
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

        # 3. Identify core files (entrypoints, key source files, manifests, excluding duplicates & docs)
        core_files: List[str] = []
        seen_basenames = set()

        entrypoint_names = {
            "main.py", "app.py", "cli.py", "index.ts", "index.js", "server.ts",
            "server.js", "lib.rs", "main.rs", "main.go", "extension.ts", "index.html"
        }

        # 1. First pass: recognized entrypoints
        for rel_path, _ in all_files:
            base = os.path.basename(rel_path)
            if base in entrypoint_names and base not in seen_basenames:
                core_files.append(rel_path)
                seen_basenames.add(base)

        # 2. Second pass: manifests
        for rel_path in profile["manifests"]:
            base = os.path.basename(rel_path)
            if rel_path not in core_files and base not in seen_basenames:
                core_files.append(rel_path)
                seen_basenames.add(base)

        # 3. Third pass: largest source code files (excluding tests, docs, configs, and duplicate basenames)
        for rel_path, _ in sorted(all_files, key=lambda x: x[1], reverse=True):
            base = os.path.basename(rel_path)
            ext = os.path.splitext(base)[1].lower()
            if ext in [".md", ".txt", ".json", ".lock", ".toml", ".yaml", ".yml"]:
                continue
            if rel_path not in core_files and rel_path not in profile["test_files"] and base not in seen_basenames:
                core_files.append(rel_path)
                seen_basenames.add(base)
        # 4. Fallback if core_files is empty (e.g. documentation-only or minimal repos)
        if not core_files:
            for rel_path, _ in all_files:
                base = os.path.basename(rel_path)
                if base not in seen_basenames:
                    core_files.append(rel_path)
                    seen_basenames.add(base)
                if len(core_files) >= 5:
                    break

        profile["core_files"] = core_files

        # 4. Detect framework and test command if not explicitly supplied
        if not profile["test_command"]:
            profile["test_command"] = RepoInspector._detect_test_command(real_ws_path, profile)

        return ProjectProfile(profile)

    @staticmethod
    def resolve_verification_command(
        workspace_path: str,
        target_file: Optional[str] = None,
        profile: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Infer or synthesize a safe, non-destructive verification command for the workspace
        or for a specific target file being repaired.

        Supports:
        - Manifest-defined test suites: npm test, pytest, cargo test, go test
        - Manifest build/lint suites: npm run build, npm run check, npm run lint
        - Target-file syntax & compiler verification:
            * JavaScript/Node: node --check <file>.js
            * Python: pytest <targeted_test> or python3 -m py_compile <file>.py
            * HTML: python3 -m html.parser <file>.html
            * JSON: python3 -m json.tool <file>.json
            * Rust: cargo check
            * Go: go vet ./...
        - Full-repo syntax fallbacks when no explicit tests exist:
            * Python: python3 -m py_compile <entrypoint> or python3 -m compileall -q .
            * JavaScript: node --check <primary_js_file>
            * Static HTML: python3 -m html.parser index.html
        """
        # 1. Target-file specific verification if target_file is supplied
        if target_file:
            clean_target = os.path.normpath(target_file.replace("\\", "/")).lstrip("/")
            if os.path.isfile(os.path.join(workspace_path, clean_target)):
                # JavaScript / Node
                if clean_target.endswith((".js", ".mjs", ".cjs")):
                    return f"node --check {clean_target}"
                
                # Python
                if clean_target.endswith((".py", ".pyw")):
                    stem = os.path.splitext(os.path.basename(clean_target))[0]
                    test_candidates = [
                        f"test_{stem}.py",
                        f"{stem}_test.py",
                        f"tests/test_{stem}.py",
                        f"backend/tests/test_{stem}.py",
                        f"test/test_{stem}.py",
                    ]
                    for cand in test_candidates:
                        if os.path.isfile(os.path.join(workspace_path, cand)):
                            return f"pytest {cand}"
                    return f"python3 -m py_compile {clean_target}"
                
                # HTML
                if clean_target.endswith((".html", ".htm")):
                    return f"python3 -m html.parser {clean_target}"
                
                # JSON
                if clean_target.endswith(".json"):
                    return f"python3 -m json.tool {clean_target}"
                
                # Rust
                if clean_target.endswith(".rs"):
                    return "cargo check"
                
                # Go
                if clean_target.endswith(".go"):
                    return "go vet ./..."

        # 2. Check root package.json for test, check, lint, or build scripts
        pkg_json_path = os.path.join(workspace_path, "package.json")
        if os.path.isfile(pkg_json_path):
            try:
                with open(pkg_json_path, "r", encoding="utf-8", errors="ignore") as f:
                    data = json.load(f)
                    scripts = data.get("scripts", {})
                    if "test" in scripts and "no test specified" not in scripts["test"] and scripts["test"].strip():
                        return "npm test"
                    elif "check" in scripts and scripts["check"].strip():
                        return "npm run check"
                    elif "typecheck" in scripts and scripts["typecheck"].strip():
                        return "npm run typecheck"
                    elif "lint" in scripts and scripts["lint"].strip():
                        return "npm run lint"
                    elif "build" in scripts and scripts["build"].strip():
                        return "npm run build"
            except Exception:
                pass

        # 3. Check nested package.json manifests (e.g. extension/ or frontend/)
        manifests = (profile.get("manifests") if profile else []) or []
        for manifest in manifests:
            if manifest.endswith("package.json"):
                pkg_path = os.path.join(workspace_path, manifest)
                try:
                    with open(pkg_path, "r", encoding="utf-8", errors="ignore") as f:
                        data = json.load(f)
                        scripts = data.get("scripts", {})
                        dir_name = os.path.dirname(manifest)
                        prefix_arg = f"--prefix {dir_name} " if dir_name else ""
                        if "test" in scripts and "no test specified" not in scripts["test"] and scripts["test"].strip():
                            return f"npm {prefix_arg}test".strip()
                        elif "check" in scripts and scripts["check"].strip():
                            return f"npm {prefix_arg}run check".strip()
                        elif "build" in scripts and scripts["build"].strip():
                            return f"npm {prefix_arg}run build".strip()
                except Exception:
                    pass

        # 4. Python repository inspection
        languages = (profile.get("languages") if profile else []) or []
        test_files = (profile.get("test_files") if profile else []) or []
        if "Python" in languages or any(f.endswith(".py") for f in test_files):
            if test_files:
                return "pytest"
            # No dedicated test files found: synthesize compilation/syntax verification
            core_files = (profile.get("core_files") if profile else []) or []
            py_core = [f for f in core_files if f.endswith((".py", ".pyw"))]
            if py_core:
                entrypoints = [f for f in py_core if os.path.basename(f) in {"main.py", "app.py", "cli.py", "server.py"}]
                target = entrypoints[0] if entrypoints else py_core[0]
                return f"python3 -m py_compile {target}"
            return "python3 -m compileall -q ."

        # 5. Vanilla JavaScript / Static Web project inspection
        if "JavaScript" in languages:
            core_files = (profile.get("core_files") if profile else []) or []
            js_core = [f for f in core_files if f.endswith((".js", ".mjs", ".cjs"))]
            if js_core:
                entrypoints = [f for f in js_core if os.path.basename(f) in {"index.js", "main.js", "app.js", "server.js", "script.js"}]
                target = entrypoints[0] if entrypoints else js_core[0]
                return f"node --check {target}"
            # Check for any .js file at workspace root
            try:
                for fname in sorted(os.listdir(workspace_path)):
                    if fname.endswith((".js", ".mjs")) and os.path.isfile(os.path.join(workspace_path, fname)):
                        return f"node --check {fname}"
            except Exception:
                pass

        # 6. Static HTML projects (e.g. index.html canvas games, web apps)
        if os.path.isfile(os.path.join(workspace_path, "index.html")):
            return "python3 -m html.parser index.html"
        if "HTML" in languages:
            core_files = (profile.get("core_files") if profile else []) or []
            html_core = [f for f in core_files if f.endswith((".html", ".htm"))]
            if html_core:
                return f"python3 -m html.parser {html_core[0]}"

        # 7. Rust check
        if "Rust" in languages:
            return "cargo test"

        # 8. Go check
        if "Go" in languages:
            return "go test ./..."

        return ""

    @staticmethod
    def _detect_test_command(workspace_path: str, profile: Dict[str, Any]) -> str:
        """Infer safe test command based on manifests and language structure."""
        return RepoInspector.resolve_verification_command(workspace_path, target_file=None, profile=profile)

    @staticmethod
    def build_bounded_context(workspace_path: str, profile: Optional[Dict[str, Any]] = None, max_total_chars: int = 14000) -> str:
        """Construct bounded, security-redacted code context for LLM investigation."""
        real_ws_path = os.path.realpath(workspace_path)
        if profile is None:
            profile = RepoInspector.inspect(real_ws_path)
        snippets: List[str] = []
        total_chars = 0
        seen_basenames = set()

        # Prioritize core files + up to 1 test file (if not already included)
        target_files = list(profile.get("core_files", []))
        test_files = profile.get("test_files", [])[:1]
        for tf in test_files:
            if tf not in target_files:
                target_files.append(tf)

        PROGRAMMING_EXTS = {
            '.py', '.ts', '.tsx', '.js', '.jsx', '.rs', '.go', '.c', '.cpp',
            '.h', '.hpp', '.java', '.esy', '.sh'
        }
        has_code_files = any(os.path.splitext(f)[1].lower() in PROGRAMMING_EXTS for f in target_files)

        for rel_path in target_files:
            base = os.path.basename(rel_path)
            # Skip documentation files from code blocks if actual source code files exist (overview already captures README summary)
            ext = os.path.splitext(base)[1].lower()
            if has_code_files and ext in [".md", ".txt"]:
                continue
            if base in seen_basenames:
                continue

            full_path = os.path.join(real_ws_path, rel_path)
            if not os.path.isfile(full_path):
                continue

            try:
                if os.path.getsize(full_path) > 100 * 1024:
                    snippet = f"--- {rel_path} ---\n[File truncated: Too large]\n"
                    snippets.append(snippet)
                    total_chars += len(snippet)
                    seen_basenames.add(base)
                    continue

                # Per-file cap to prevent single-file domination
                file_cap = 3500
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
                seen_basenames.add(base)
            except Exception as e:
                logger.debug(f"Could not read file {rel_path}: {e}")

        return "\n".join(snippets)
