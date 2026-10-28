import os
import re
import difflib
import subprocess
import logging
from unidiff import PatchSet

logger = logging.getLogger(__name__)

def normalize_diff_indentation(patch: str) -> str:
    """Strip common leading indentation added to hunk lines by model pretty-printing."""
    lines = patch.splitlines()
    in_hunk = False
    hunk_lines_indices = []
    for idx, line in enumerate(lines):
        if line.startswith("@@"):
            in_hunk = True
            continue
        if in_hunk:
            if line.startswith("--- ") or line.startswith("diff --git "):
                in_hunk = False
            else:
                hunk_lines_indices.append(idx)

    if not hunk_lines_indices:
        return patch

    context_lines = [lines[idx] for idx in hunk_lines_indices if lines[idx].startswith("  ")]
    all_context = [lines[idx] for idx in hunk_lines_indices if lines[idx].startswith(" ")]
    if context_lines and len(context_lines) == len(all_context):
        extra_spaces = min(len(l) - len(l.lstrip()) for l in context_lines) - 1
        if extra_spaces > 0:
            fixed = []
            for idx, line in enumerate(lines):
                if idx in hunk_lines_indices:
                    if line.startswith(" "):
                        fixed.append(" " + line[1 + extra_spaces:])
                    elif line.startswith("-") and line[1:].startswith(" " * extra_spaces):
                        fixed.append("-" + line[1 + extra_spaces:])
                    elif line.startswith("+") and line[1:].startswith(" " * extra_spaces):
                        fixed.append("+" + line[1 + extra_spaces:])
                    else:
                        fixed.append(line)
                else:
                    fixed.append(line)
            return "\n".join(fixed) + "\n"

    return patch

def fix_hunk_headers(patch: str) -> str:
    """Recount lines in hunk headers so git apply does not fail on LLM arithmetic mismatches."""
    lines = patch.splitlines()
    fixed_lines = []
    i = 0
    hunk_header_re = re.compile(r"^@@\s*-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s*@@(.*)$")

    while i < len(lines):
        line = lines[i]
        m = hunk_header_re.match(line)
        if m:
            old_start = m.group(1)
            new_start = m.group(2)
            suffix = m.group(3)

            j = i + 1
            old_count = 0
            new_count = 0
            while j < len(lines):
                next_line = lines[j]
                if next_line.startswith("@@") or next_line.startswith("--- ") or next_line.startswith("diff --git "):
                    break
                if next_line.startswith("-"):
                    old_count += 1
                elif next_line.startswith("+"):
                    new_count += 1
                elif next_line.startswith(" ") or next_line == "":
                    old_count += 1
                    new_count += 1
                elif next_line.startswith("\\ No newline at end of file"):
                    pass
                else:
                    break
                j += 1

            new_header = f"@@ -{old_start},{old_count} +{new_start},{new_count} @@{suffix}"
            fixed_lines.append(new_header)
            i += 1
        else:
            fixed_lines.append(line)
            i += 1

    return "\n".join(fixed_lines) + "\n"

class PatchEngine:
    @staticmethod
    def apply_patch(workspace_path: str, patch_content: str) -> bool:
        if not patch_content or not patch_content.strip():
            return False

        sanitized_patch = fix_hunk_headers(normalize_diff_indentation(patch_content))
        patch_file_path = os.path.join(workspace_path, "repair.patch")
        try:
            with open(patch_file_path, "w") as f:
                f.write(sanitized_patch)

            # Security Path Validation
            target_files = []
            try:
                patch_set = PatchSet(sanitized_patch)
                target_files = [patched_file.target_file for patched_file in patch_set]
            except Exception as pe:
                logger.debug(f"Unidiff parse failed ({pe}), falling back to regex header extraction")
                # Fallback extraction from +++ b/<path> or +++ <path>
                raw_targets = re.findall(r'^[+]{3}\s+(?:b/)?(\S+)', sanitized_patch, re.MULTILINE)
                if not raw_targets:
                    # Also check --- a/<path>
                    raw_targets = re.findall(r'^[-]{3}\s+(?:a/)?(\S+)', sanitized_patch, re.MULTILINE)
                target_files = raw_targets

            if not target_files:
                logger.warning("No target files identified in patch")
                return False

            for raw_path in target_files:
                clean_target = raw_path
                if clean_target.startswith("b/") or clean_target.startswith("a/"):
                    clean_target = clean_target[2:]
                target_path = os.path.normpath(clean_target)

                # Prevent absolute paths or path traversal
                if target_path.startswith("..") or target_path.startswith("/") or target_path.startswith("\\"):
                    logger.warning(f"Invalid path in patch: {target_path}")
                    return False

                # Prevent changes outside workspace
                abs_target = os.path.abspath(os.path.join(workspace_path, target_path))
                if not abs_target.startswith(os.path.abspath(workspace_path)):
                    logger.warning(f"Target path outside workspace: {target_path}")
                    return False

                # Prevent modifying binary files implicitly by checking path
                if any(target_path.endswith(ext) for ext in ['.exe', '.dll', '.so', '.pyc', '.zip', '.tar.gz']):
                    logger.warning(f"Patching binary files is not allowed: {target_path}")
                    return False

            # Primary: Standard git apply
            result = subprocess.run(
                ["git", "apply", "repair.patch"],
                cwd=workspace_path,
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                return True

            # Fallback 1: git apply with whitespace tolerance
            logger.info("Retrying git apply with whitespace tolerance")
            result_whitespace = subprocess.run(
                ["git", "apply", "--ignore-space-change", "--ignore-whitespace", "repair.patch"],
                cwd=workspace_path,
                capture_output=True,
                text=True
            )

            if result_whitespace.returncode == 0:
                return True

            # Fallback 2: git apply with reduced context tolerance (C1 ensures at least 1 line matches)
            result_c1 = subprocess.run(
                ["git", "apply", "-C1", "--ignore-space-change", "--ignore-whitespace", "repair.patch"],
                cwd=workspace_path,
                capture_output=True,
                text=True
            )

            if result_c1.returncode == 0:
                return True

            # Fallback 3: git apply with 3way merge
            result_3way = subprocess.run(
                ["git", "apply", "--3way", "--ignore-space-change", "--ignore-whitespace", "repair.patch"],
                cwd=workspace_path,
                capture_output=True,
                text=True
            )

            if result_3way.returncode == 0:
                return True

            # Fallback 4: patch utility (handles line offsets and whitespace variations safely)
            result_patch_cmd = subprocess.run(
                ["patch", "-p1", "--batch", "-N", "-i", "repair.patch"],
                cwd=workspace_path,
                capture_output=True,
                text=True
            )

            if result_patch_cmd.returncode == 0:
                logger.info("Patch applied successfully via patch utility")
                return True

            # Fallback 5: Semantic fuzzy chunk ingestion (handles LLM indentation drops and line miscalculations)
            logger.info("Retrying patch via semantic fuzzy chunk ingestion")
            if PatchEngine.fuzzy_apply_patch(workspace_path, sanitized_patch):
                return True

            logger.error(f"Failed to apply patch: {result.stderr or result_whitespace.stderr or result_patch_cmd.stderr}")
            return False

        except Exception as e:
            logger.error(f"Error applying patch: {e}")
            return False
        finally:
            if os.path.exists(patch_file_path):
                os.remove(patch_file_path)

    @staticmethod
    def fuzzy_apply_patch(workspace_path: str, patch_content: str) -> bool:
        """
        Semantic chunk replacement fallback for LLM-generated diffs where:
        - Line numbers are approximate.
        - Leading indentation was stripped or inconsistent.
        - Surrounding context has minor variations.
        """
        file_sections = re.split(r"(?=(?:^diff --git |^--- ))", patch_content, flags=re.MULTILINE)
        modified_any = False

        for section in file_sections:
            if not section.strip():
                continue

            match_plus = re.search(r"^\+\+\+\s+(?:b/)?(\S+)", section, re.MULTILINE)
            if not match_plus:
                match_minus = re.search(r"^---\s+(?:a/)?(\S+)", section, re.MULTILINE)
                if not match_minus:
                    continue
                target_rel = match_minus.group(1)
            else:
                target_rel = match_plus.group(1)

            target_rel = os.path.normpath(target_rel)
            if target_rel.startswith("..") or target_rel.startswith("/") or target_rel.startswith("\\"):
                continue

            abs_target = os.path.abspath(os.path.join(workspace_path, target_rel))
            if not abs_target.startswith(os.path.abspath(workspace_path)):
                continue

            if not os.path.isfile(abs_target):
                continue

            try:
                with open(abs_target, "r", errors="ignore") as f:
                    file_content = f.read()
            except Exception:
                continue

            hunk_pattern = re.compile(r"^@@\s*-\d+(?:,\d+)?\s+\+\d+(?:,\d+)?\s*@@.*$", re.MULTILINE)
            hunk_splits = list(hunk_pattern.finditer(section))
            if not hunk_splits:
                continue

            file_modified = False

            for idx, m in enumerate(hunk_splits):
                start_pos = m.end()
                end_pos = hunk_splits[idx + 1].start() if idx + 1 < len(hunk_splits) else len(section)
                hunk_body = section[start_pos:end_pos].splitlines()

                minus_lines = []
                plus_lines = []
                context_before = []
                context_after = []
                seen_change = False

                for raw_line in hunk_body:
                    if not raw_line:
                        continue
                    prefix = raw_line[0]
                    val = raw_line[1:].strip()
                    if not val:
                        continue
                    if prefix == "-":
                        minus_lines.append(val)
                        seen_change = True
                    elif prefix == "+":
                        plus_lines.append(val)
                        seen_change = True
                    elif prefix == " ":
                        if not seen_change:
                            context_before.append(val)
                        else:
                            context_after.append(val)

                target_lines = file_content.splitlines()
                target_indices = [i for i, line in enumerate(target_lines) if line.strip()]
                target_stripped = [target_lines[i].strip() for i in target_indices]

                if not target_stripped:
                    continue

                # Case 1: Targeted Replacement / Deletion (minus_lines present)
                if minus_lines:
                    found_minus_idx = -1
                    for i in range(len(target_stripped) - len(minus_lines) + 1):
                        if target_stripped[i:i + len(minus_lines)] == minus_lines:
                            ctx_ok = False
                            if not context_before and not context_after:
                                ctx_ok = True
                            else:
                                window = target_stripped[max(0, i - 8):min(len(target_stripped), i + len(minus_lines) + 8)]
                                if any(c in window for c in (context_before + context_after)):
                                    ctx_ok = True
                            if ctx_ok:
                                found_minus_idx = i
                                break

                    if found_minus_idx != -1:
                        match_start = target_indices[found_minus_idx]
                        match_end = target_indices[found_minus_idx + len(minus_lines) - 1]
                        first_line = target_lines[match_start]
                        base_indent = first_line[:len(first_line) - len(first_line.lstrip())]
                        new_lines = [f"{base_indent}{val}" for val in plus_lines]

                        new_target_lines = target_lines[:match_start] + new_lines + target_lines[match_end + 1:]
                        file_content = "\n".join(new_target_lines)
                        file_modified = True
                        continue

                # Case 2: Pure addition or fuzzy hunk window
                all_hunk_search = context_before + minus_lines + context_after
                if all_hunk_search and len(target_stripped) >= len(all_hunk_search):
                    best_ratio = 0.0
                    best_i = -1
                    w_len = len(all_hunk_search)
                    for i in range(len(target_stripped) - w_len + 1):
                        window = target_stripped[i:i + w_len]
                        ratio = difflib.SequenceMatcher(None, all_hunk_search, window).ratio()
                        if ratio > best_ratio:
                            best_ratio = ratio
                            best_i = i

                    if best_ratio >= 0.65 and best_i != -1:
                        match_start = target_indices[best_i]
                        match_end = target_indices[min(len(target_indices) - 1, best_i + w_len - 1)]
                        first_line = target_lines[match_start]
                        base_indent = first_line[:len(first_line) - len(first_line.lstrip())]
                        new_lines = [f"{base_indent}{val}" for val in (context_before + plus_lines + context_after)]
                        new_target_lines = target_lines[:match_start] + new_lines + target_lines[match_end + 1:]
                        file_content = "\n".join(new_target_lines)
                        file_modified = True

            if file_modified:
                with open(abs_target, "w") as f:
                    f.write(file_content)
                modified_any = True

        if modified_any:
            try:
                diff_proc = subprocess.run(
                    ["git", "diff", "--name-only"],
                    cwd=workspace_path,
                    capture_output=True,
                    text=True
                )
                if diff_proc.returncode == 0 and diff_proc.stdout.strip():
                    logger.info("Patch applied successfully via semantic fuzzy chunk ingestion")
                    return True
            except Exception as e:
                logger.error(f"Fuzzy apply git check error: {e}")

        return False
