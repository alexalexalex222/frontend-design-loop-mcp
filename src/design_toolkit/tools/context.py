"""build_context - build a repo context blob for the agent."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from design_toolkit.utils import merge_unique, read_text, run_command

_SENSITIVE_PATTERNS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.keystore",
    ".npmrc",
    ".pypirc",
    ".netrc",
    ".git-credentials",
    "id_*",
    "*secret*",
    "*secrets*",
    "*credential*",
    "*credentials*",
    "*token*",
    "*oauth*",
    "service-account*.json",
)

_SENSITIVE_DIR_PREFIXES = (
    ".git/",
    ".aws/",
    ".ssh/",
    ".config/gcloud/",
    ".docker/",
    ".kube/",
)

_REDACTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)\b(authorization\s*:\s*bearer\s+)([^\s\"']+)"), r"\1[REDACTED]"),
    (re.compile(r"(?i)\b(cookie\s*:\s*)([^;\n]+)"), r"\1[REDACTED]"),
    (
        re.compile(
            r"(?i)\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY|ACCESS_KEY|CLIENT_SECRET|AUTH)[A-Z0-9_]*)=([^\s]+)"
        ),
        r"\1=[REDACTED]",
    ),
    (re.compile(r"(?i)https?://([^/\s:@]+):([^/\s@]+)@"), r"[REDACTED]:[REDACTED]@"),
]

_AUTO_CONTEXT_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "do",
    "for",
    "from",
    "how",
    "i",
    "if",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "we",
    "what",
    "when",
    "where",
    "with",
    "you",
    "your",
}


def is_sensitive_path(rel_path: str) -> bool:
    rel = str(rel_path or "").replace("\\", "/").strip()
    while rel.startswith("./"):
        rel = rel[2:]
    rel = rel.lstrip("/")
    if not rel:
        return False
    name = Path(rel).name.lower()
    lower_rel = rel.lower()

    if any(fnmatch.fnmatch(name, pattern) for pattern in _SENSITIVE_PATTERNS):
        return True
    for prefix in _SENSITIVE_DIR_PREFIXES:
        if lower_rel.startswith(prefix) or f"/{prefix}" in lower_rel:
            return True
    return False


def redact_sensitive_text(text: str | None) -> str:
    value = str(text or "")
    for pattern, replacement in _REDACTION_PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def build_context_blob(
    *,
    repo_root: Path,
    context_files: list[str],
    max_file_chars: int = 12_000,
    max_total_chars: int | None = 150_000,
) -> str:
    """Build a context blob from repo files."""
    blobs: list[str] = []
    repo_resolved = repo_root.resolve()
    total = 0
    truncated = False

    for rel in context_files:
        rel = str(rel or "").strip()
        if not rel:
            continue
        if is_sensitive_path(rel):
            continue
        path = (repo_root / rel).resolve()
        try:
            path.relative_to(repo_resolved)
        except Exception:
            continue

        text = redact_sensitive_text(read_text(path, max_chars=max_file_chars))
        if not text.strip():
            continue

        block = f"=== {rel} ===\n{text}"
        if max_total_chars and total + len(block) > max_total_chars:
            truncated = True
            break
        blobs.append(block)
        total += len(block) + 2

    if truncated:
        blobs.append("...(context truncated)...")
    return "\n\n".join(blobs).strip()


def derive_auto_context_queries(goal: str, *, max_queries: int = 8) -> list[str]:
    """Extract search queries from a goal string."""
    tokens = re.split(r"[^A-Za-z0-9_]+", str(goal or ""))
    cleaned = [token.strip().lower() for token in tokens if len(token.strip()) >= 4]
    cleaned = [token for token in cleaned if token not in _AUTO_CONTEXT_STOPWORDS]
    cleaned = sorted(merge_unique(cleaned), key=len, reverse=True)
    return cleaned[:max_queries]


async def auto_context_files(
    *,
    repo_root: Path,
    queries: list[str],
    max_files: int = 20,
) -> list[str]:
    """Find relevant files in a repo by searching for query terms."""
    repo_resolved = repo_root.resolve()
    queries = [query.strip() for query in queries if str(query).strip()]
    if not queries or max_files <= 0:
        return []

    rc, out, _ = await run_command("command -v rg", cwd=repo_root, timeout_ms=5000)
    has_rg = rc == 0 and bool((out or "").strip())

    ignore_globs = [
        "!.git/**",
        "!node_modules/**",
        "!.venv/**",
        "!venv/**",
        "!__pycache__/**",
        "!out/**",
        "!.next/**",
        "!dist/**",
        "!build/**",
        "!coverage/**",
        "!*.png",
        "!*.jpg",
        "!*.jpeg",
        "!*.webp",
        "!*.gif",
        "!*.pdf",
        "!*.zip",
    ]

    def _filter(lines: list[str]) -> list[str]:
        result: list[str] = []
        for line in lines:
            rel = str(line or "").strip().replace("\\", "/")
            if not rel or rel.startswith(("/", "../")) or "/../" in rel:
                continue
            path = (repo_root / rel).resolve()
            try:
                path.relative_to(repo_resolved)
            except Exception:
                continue
            if not path.exists() or not path.is_file():
                continue
            if is_sensitive_path(rel):
                continue
            result.append(rel)
        return result

    found: list[str] = []
    for query in queries:
        if len(found) >= max_files:
            break

        if has_rg:
            from design_toolkit.utils import shlex_quote

            glob_flags = " ".join(f"--glob {shlex_quote(glob)}" for glob in ignore_globs)
            cmd = f"rg -l -F -i --hidden --no-messages {glob_flags} {shlex_quote(query)}"
        else:
            cmd = (
                "grep -RIl --binary-files=without-match "
                "--exclude-dir=.git --exclude-dir=node_modules --exclude-dir=out "
                "--exclude-dir=.venv --exclude-dir=venv --exclude-dir=__pycache__ "
                "--exclude-dir=.next --exclude-dir=dist --exclude-dir=build "
                f"{query} ."
            )

        rc, out, _ = await run_command(cmd, cwd=repo_root, timeout_ms=30_000)
        if rc in (0, 1) and out:
            found.extend(_filter(out.splitlines()))

    return merge_unique(found)[:max_files]
