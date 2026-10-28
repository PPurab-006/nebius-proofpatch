"""
Reporting and repository presentation module for Patchworks.

Enforces professional, concise, emoji-free, engineering-grade writing standards
for all GitHub-facing text (pull requests, commit messages, titles, and verification reports).
"""

import re
from typing import Dict, Any, List, Optional

# Emoji and decorative Unicode pattern.
# Strips emoji symbols and pictographs without stripping standard alphanumeric,
# common punctuation, technical symbols, or non-Latin alphabet characters.
EMOJI_PATTERN = re.compile(
    r"[\U00010000-\U0010ffff]"  # SMP symbols (emojis, pictographs)
    r"|[\u2600-\u27bf]"          # Miscellaneous symbols & dingbats
    r"|[\u2300-\u23ff]"          # Miscellaneous technical symbols
    r"|[\u2b50-\u2b55]"          # Stars & geometric symbols
    r"|[\ufe00-\ufe0f]"          # Variation selectors
    r"|[\u200d]"                 # Zero-width joiner
)

# Common promotional phrases to omit from repository-facing text
PROMOTIONAL_PATTERNS = [
    re.compile(r"(?i)\*?created\s+autonomously\s+with\s+(?:\[?patchworks\]?[^\n.]*)[\s\S]*?(?:\.|\n|$)", re.IGNORECASE),
    re.compile(r"(?i)\*?autonomously\s+repaired\s+and\s+verified\s+by\s+patchworks\.?", re.IGNORECASE),
    re.compile(r"(?i)find\s+the\s+fault\.\s*forge\s+the\s+fix\.\s*prove\s+it\s+works\.?", re.IGNORECASE),
    re.compile(r"(?i)official\s+autonomous\s+code-repair\s+audit\s+report\.?", re.IGNORECASE),
    re.compile(r"(?i)patchworks\s+verified\s+code\s+repair\.?", re.IGNORECASE),
]

# Sensitive patterns to redact from logs, test output, and prose
SECRET_PATTERNS = [
    (re.compile(r"\b(gh[pousr]_[A-Za-z0-9_]{20,})\b"), r"[REDACTED_TOKEN]"),
    (re.compile(r"\b(github_pat_[A-Za-z0-9_]{20,})\b"), r"[REDACTED_TOKEN]"),
    (re.compile(r"\b(sk-[A-Za-z0-9_-]{20,})\b"), r"[REDACTED_KEY]"),
    (re.compile(r"(?i)\b(bearer\s+)([A-Za-z0-9._~+/-]+=*)"), r"\1[REDACTED]"),
    (re.compile(r"(?i)\b(basic\s+)([A-Za-z0-9+/=]+)"), r"\1[REDACTED]"),
    (re.compile(r"(?i)\b((?:API_KEY|TOKEN|SECRET|PASSWORD|AUTH_KEY)\s*=\s*)([\"']?)(?:[A-Za-z0-9_.~+-]{8,})\2"), r"\1\2[REDACTED]\2"),
]


def strip_emojis(text: str) -> str:
    """Strip emojis and decorative symbols from prose text."""
    if not text:
        return ""
    cleaned = EMOJI_PATTERN.sub("", text)
    # Collapse multiple consecutive spaces created by emoji stripping
    return re.sub(r"[ \t]{2,}", " ", cleaned)


def redact_secrets(text: str) -> str:
    """Redact sensitive tokens, keys, and authorization headers."""
    if not text:
        return ""
    result = text
    for pattern, replacement in SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def clean_prose(text: str) -> str:
    """
    Clean Patchworks-authored prose by stripping emojis, redacting secrets,
    and removing marketing / promotional statements.
    Preserves meaningful technical terminology, filenames, and line numbers.
    """
    if not text:
        return ""

    result = redact_secrets(text)
    result = strip_emojis(result)

    for pat in PROMOTIONAL_PATTERNS:
        result = pat.sub("", result)

    # Normalize excessive blank lines
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def format_commit_title(title: str) -> str:
    """Format a clean, conventional commit title (<= 72 chars, emoji-free)."""
    clean = clean_prose(title)
    # Take first line if multi-line
    clean = clean.split("\n")[0].strip()
    clean = clean.rstrip(".")
    if not clean:
        clean = "resolve issue in codebase"

    # Add fix: prefix if no standard conventional commit prefix is present
    has_prefix = bool(re.match(r"^(fix|feat|chore|refactor|test|docs|perf|ci)(\([a-zA-Z0-9_-]+\))?:", clean, re.IGNORECASE))
    if not has_prefix:
        clean = f"fix: {clean}"

    if len(clean) > 72:
        clean = clean[:69].rstrip() + "..."
    return clean


def format_commit_message(title: str, summary: Optional[str] = None) -> str:
    """Format a clean, production commit message without promotional footers."""
    subject = format_commit_title(title)
    if not summary:
        return subject

    clean_summary = clean_prose(summary)
    # Avoid duplicating subject in body
    if clean_summary and clean_summary.lower() != subject.lower():
        # Keep body concise
        lines = [line.strip() for line in clean_summary.split("\n") if line.strip()]
        body = "\n".join(lines[:6])
        if body and body.lower() not in subject.lower():
            return f"{subject}\n\n{body}"
    return subject


def format_pr_title(title: str) -> str:
    """Format a concise, professional pull request title."""
    clean = clean_prose(title)
    clean = clean.split("\n")[0].strip()
    clean = clean.rstrip(".")
    if not clean:
        return "Fix defect in target repository"
    if len(clean) > 80:
        clean = clean[:77].rstrip() + "..."
    return clean


def format_pull_request_body(
    title: str,
    problem_summary: str,
    diagnosis_data: Optional[Dict[str, Any]],
    verification_details: Optional[Dict[str, Any]],
    model_name: str,
    is_mock_mode: bool,
    new_branch: str,
    target_branch: str,
    commit_sha: str,
    custom_notes: Optional[str] = None,
    finding_fingerprints: Optional[List[str]] = None,
    finding_ids: Optional[List[str]] = None
) -> str:
    """
    Construct a clean, professional Pull Request markdown body conforming to:
    - Sentence case headings: Summary, Root cause, Changes, Verification, Risk assessment
    - Emoji-free, banner-free, marketing-free presentation
    - Truthful, rigorous verification reporting (never claiming verification without passing tests)
    - Sensitive data redaction
    - Omission of empty or redundant sections
    """
    diag = diagnosis_data or {}
    sections: List[str] = []

    # 1. Summary
    summary_parts: List[str] = []
    clean_problem = clean_prose(problem_summary)
    if clean_problem and clean_problem.lower() != "autonomously repaired bug":
        summary_parts.append(clean_problem)
    elif title:
        summary_parts.append(format_pr_title(title))

    proposed_fix = clean_prose(diag.get("proposed_fix_description", ""))
    if proposed_fix and proposed_fix.lower() not in (clean_problem or "").lower():
        summary_parts.append(proposed_fix)

    if custom_notes:
        clean_notes = clean_prose(custom_notes)
        if clean_notes:
            summary_parts.append(f"**Review notes:**\n{clean_notes}")

    if summary_parts:
        sections.append("## Summary\n" + "\n\n".join(summary_parts))

    # 2. Root cause
    root_cause_parts: List[str] = []
    raw_diag = diag.get("diagnosis", "").strip()
    clean_diag = clean_prose(raw_diag)

    # Check for unconfirmed / uncertain root cause
    is_uncertain = (
        not clean_diag
        or any(w in clean_diag.lower() for w in ["unknown", "uncertain", "not configured", "cannot evaluate"])
    )

    if clean_diag:
        root_cause_parts.append(clean_diag)
    elif is_uncertain:
        root_cause_parts.append("Root cause has not been definitively confirmed from available context.")

    raw_evidence = diag.get("evidence", "").strip()
    if raw_evidence:
        # Redact secrets in evidence while preserving code formatting
        clean_evidence = redact_secrets(raw_evidence).strip()
        # Omit generic placeholder evidence
        if clean_evidence and clean_evidence.lower() not in ["code context analysis", "context inspection", "none"]:
            if "\n" in clean_evidence or len(clean_evidence) > 80:
                root_cause_parts.append(f"**Evidence:**\n```\n{clean_evidence}\n```")
            else:
                root_cause_parts.append(f"**Evidence:** {clean_evidence}")

    if root_cause_parts:
        sections.append("## Root cause\n" + "\n\n".join(root_cause_parts))

    # 3. Changes
    files_to_modify = diag.get("files_to_modify", [])
    if isinstance(files_to_modify, list) and files_to_modify:
        valid_files = [f.strip() for f in files_to_modify if isinstance(f, str) and f.strip()]
        if valid_files:
            file_bullets = "\n".join([f"- `{f}`" for f in valid_files])
            sections.append(f"## Changes\n{file_bullets}")

    # 4. Verification
    verif_parts: List[str] = []
    if verification_details and isinstance(verification_details, dict):
        returncode = verification_details.get("returncode")
        success = verification_details.get("success")
        is_success = (returncode == 0 and success is not False)

        if is_success:
            verif_parts.append("- **Status:** FIX VERIFIED (test command exited with code 0)")
        elif returncode == -1:
            verif_parts.append("- **Status:** VERIFICATION INCOMPLETE (execution timed out or could not be run)")
        elif returncode is not None:
            verif_parts.append(f"- **Status:** FIX FAILED (test command exited with non-zero code {returncode})")
        else:
            verif_parts.append("- **Status:** UNVERIFIED")

        if returncode is not None and returncode != -1:
            verif_parts.append(f"- **Exit code:** `{returncode}`")

        stdout = verification_details.get("stdout", "").strip()
        stderr = verification_details.get("stderr", "").strip()

        if stdout:
            clean_stdout = redact_secrets(stdout)
            if len(clean_stdout) > 2500:
                clean_stdout = clean_stdout[:2500] + "\n... [Output truncated]"
            verif_parts.append(f"**Test output:**\n```\n{clean_stdout}\n```")

        if stderr and returncode != 0:
            clean_stderr = redact_secrets(stderr)
            if len(clean_stderr) > 1500:
                clean_stderr = clean_stderr[:1500] + "\n... [Error output truncated]"
            verif_parts.append(f"**Error output:**\n```\n{clean_stderr}\n```")

        verif_parts.append("Note: Additional full regression suites were not executed in this sandbox.")
    else:
        verif_parts.append("- **Status:** UNVERIFIED (no automated test suite was executed for this workspace)")
        verif_parts.append("- Relevant unit and integration tests should be run before merging.")

    sections.append("## Verification\n" + "\n".join(verif_parts))

    # 5. Risk assessment
    raw_risks = diag.get("regression_risks", "").strip()
    clean_risks = clean_prose(raw_risks)
    if clean_risks and clean_risks.lower() not in ["none", "none identified", "none specified"]:
        # If risk is just "low" without rationale, expand neutrally to indicate basis
        if clean_risks.lower() == "low":
            clean_risks = "Low expected regression risk based on targeted scope of modified files. Standard test coverage should be validated prior to deployment."
        sections.append(f"## Risk assessment\n{clean_risks}")

    # Subtle traceability metadata footer (factual, non-promotional)
    mode_desc = (
        "Simulated Mock Mode"
        if is_mock_mode
        else f"Live Nebius AI Cloud (model: `{model_name}`)"
    )
    meta_footer = (
        f"---\n"
        f"_Branch: `{new_branch}` | Target: `{target_branch}` | Commit: `{commit_sha[:8]}`_\n"
        f"_Inference: {mode_desc}_"
    )
    sections.append(meta_footer)

    # Machine-readable hidden comments for persistent PR status tracking
    hidden_comments: List[str] = []
    if finding_fingerprints:
        for fp in finding_fingerprints:
            if fp and fp.strip():
                hidden_comments.append(f"<!-- patchworks-finding-fingerprint: {fp.strip()} -->")
    if finding_ids:
        for fid in finding_ids:
            if fid and str(fid).strip():
                hidden_comments.append(f"<!-- patchworks-finding-id: {str(fid).strip()} -->")

    if hidden_comments:
        sections.append("\n".join(hidden_comments))

    return "\n\n".join(sections) + "\n"


def compute_finding_fingerprint(finding: Dict[str, Any]) -> str:
    """
    Generate a deterministic 16-character hexadecimal fingerprint for a finding.
    Based on normalized primary affected files, line numbers, category, and title.
    """
    if not finding or not isinstance(finding, dict):
        return ""
    import hashlib
    files = sorted([str(f).strip().lower() for f in finding.get("files", []) if str(f).strip()])
    line_numbers = sorted([int(n) for n in finding.get("line_numbers", []) if isinstance(n, (int, str)) and str(n).isdigit()])
    title = clean_prose(finding.get("title", "")).lower().strip()
    category = str(finding.get("category", "")).lower().strip()
    raw_str = f"{','.join(files)}|{','.join(map(str, line_numbers))}|{category}|{title}"
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()[:16]


def extract_finding_fingerprints_from_pr_body(body: str) -> List[str]:
    """Extract hidden finding fingerprint comments from PR markdown body."""
    if not body:
        return []
    return re.findall(r"<!--\s*patchworks-finding-fingerprint:\s*([a-f0-9]{16})\s*-->", body)


def extract_finding_ids_from_pr_body(body: str) -> List[str]:
    """Extract hidden finding id comments from PR markdown body."""
    if not body:
        return []
    return re.findall(r"<!--\s*patchworks-finding-id:\s*([a-zA-Z0-9_\-]+)\s*-->", body)

