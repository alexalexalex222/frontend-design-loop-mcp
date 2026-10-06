"""Validated visual evidence and replayable, reversible candidate working contents.

Git helpers export tracked working contents and eligible untracked source rather
than staged intent. Ignored, generated and sensitive untracked paths are excluded
by a recorded policy before reading contents. Changed tracked sensitive paths,
submodules, sparse checkouts and clean/smudge filters fail explicitly. This is a
path boundary, not a scanner for secrets embedded in source.
Snapshot files/fingerprints describe physical checkout bytes and types; git_files
records the separately normalized Git blob/mode metadata. Replay patches carry
physical bytes, including normalization-only differences from HEAD.
Checkpoints are for disposable candidates, never a live developer checkout.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import math
import os
import re
import shutil
import stat
import tempfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from .utils import launch_process_argv, run_process_argv, terminate_process_tree
from .utils import run_command_argv as run_argv


class VisualReportError(ValueError):
    """The evaluator did not supply a usable assessment (not a design defect)."""


class EvidenceError(RuntimeError):
    """Source cannot be represented or replayed safely and completely."""


def _number(value: Any, field: str, maximum: float, *, nullable: bool = False) -> float | None:
    if value is None and nullable:
        return None
    if type(value) not in (int, float) or not 0 <= value <= maximum or not math.isfinite(value):
        raise VisualReportError(f"{field} must be a finite number in 0..{maximum:g}")
    return float(value)


def _boolean(value: Any, field: str, *, nullable: bool = False) -> bool | None:
    if value is None and nullable:
        return None
    if type(value) is not bool:
        raise VisualReportError(f"{field} must be a boolean")
    return value


def _items(value: Any, field: str) -> list:
    if not isinstance(value, list) or any(not isinstance(item, (str, dict)) for item in value):
        raise VisualReportError(f"{field} must be an array of text or evidence objects")
    return copy.deepcopy(value)


def _finite_json(value: Any, ancestors: set[int] | None = None) -> None:
    ancestors = set() if ancestors is None else ancestors
    if isinstance(value, float) and not math.isfinite(value):
        raise VisualReportError("Report contains a non-finite number")
    if isinstance(value, (dict, list)):
        if id(value) in ancestors:
            raise VisualReportError("Report contains a circular reference")
        ancestors.add(id(value))
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise VisualReportError("Report keys must be strings")
        for child in value.values():
            _finite_json(child, ancestors)
    elif isinstance(value, list):
        for child in value:
            _finite_json(child, ancestors)
    elif value is not None and not isinstance(value, (str, bool, int, float)):
        raise VisualReportError("Report must contain JSON values")
    if isinstance(value, (dict, list)):
        ancestors.remove(id(value))


def validate_visual_report(report: dict) -> dict:
    """Normalize the legacy nested assessment or the versioned flat schema.

    Version 1 requires status, broken, score, pass, blockers, uncertainty, evidence
    and limits. Evidence requires kind (ui/proxy/insufficient), sufficient (bool),
    and observations (array). Unknown JSON fields are preserved. Legacy callers
    may omit pass and evidence; their unidentified evidence is an explicit limit.
    """
    if not isinstance(report, dict):
        raise VisualReportError("Visual report must be an object")
    _finite_json(report)
    strict = "schema_version" in report
    if strict:
        if type(report["schema_version"]) is not int or report["schema_version"] != 1:
            raise VisualReportError("Unsupported visual report schema_version")
        required = {"status", "broken", "score", "pass", "blockers", "uncertainty", "evidence", "limits"}
        if not required.issubset(report):
            raise VisualReportError("Versioned report is missing required assessments or evidence")
        broken_value = report["broken"]
        score_value = report["score"]
        score_obj: dict = {}
        broken_obj: dict = {}
    else:
        if not isinstance(report.get("broken"), dict) or not isinstance(report.get("score"), dict):
            raise VisualReportError("Legacy report requires broken and score assessment objects")
        broken_obj, score_obj = report["broken"], report["score"]
        if "broken" not in broken_obj or "score" not in score_obj:
            raise VisualReportError("Legacy report is missing a required assessment")
        broken_value, score_value = broken_obj["broken"], score_obj["score"]

    broken = _boolean(broken_value, "broken", nullable=True)
    score = _number(score_value, "score", 10, nullable=True)
    confidence = _number(report.get("confidence", broken_obj.get("confidence")), "confidence", 1, nullable=True)
    if "confidence" in broken_obj:
        nested_confidence = _number(broken_obj["confidence"], "broken.confidence", 1, nullable=True)
        if "confidence" in report and nested_confidence != confidence:
            raise VisualReportError("Conflicting confidence assessments")
    declared_pass = _boolean(report.get("pass", score_obj.get("pass")), "pass", nullable=True)
    if "pass" in report and "pass" in score_obj:
        if _boolean(score_obj["pass"], "score.pass", nullable=True) != declared_pass:
            raise VisualReportError("Conflicting pass assessments")
    # Explicit error/uncertainty must survive normalization, including old evaluators.
    status = report.get("status", score_obj.get("status", broken_obj.get("status")))
    for nested in (score_obj, broken_obj):
        if "status" in nested and status != nested["status"]:
            raise VisualReportError("Conflicting assessment statuses")
    assessment = report.get("assessment", score_obj.get("assessment", broken_obj.get("assessment")))
    for assessment_obj in (report, score_obj, broken_obj):
        if "assessment" in assessment_obj and assessment_obj["assessment"] != assessment:
            raise VisualReportError("Conflicting visual assessments")
    if assessment is not None and assessment not in ("poor", "ordinary", "good", "excellent", "uncertain"):
        raise VisualReportError("Unsupported visual assessment")
    if assessment == "uncertain":
        if status not in (None, "uncertain"):
            raise VisualReportError("Uncertainty contradicts report status")
        status = "uncertain"
    elif assessment is not None and score is None:
        raise VisualReportError("Supported visual assessments require a score")
    error = report.get("error", score_obj.get("error", broken_obj.get("error")))
    uncertainty = _items(report.get("uncertainty", score_obj.get("uncertainty", [])), "uncertainty")
    for assessment_obj in (report, score_obj, broken_obj):
        if "uncertain" in assessment_obj and _boolean(assessment_obj["uncertain"], "uncertain"):
            if status not in (None, "uncertain"):
                raise VisualReportError("Uncertainty contradicts report status")
            uncertainty.append("Evaluator marked the assessment uncertain")
            status = status or "uncertain"
    if error is not None:
        if not isinstance(error, str) or not error.strip():
            raise VisualReportError("error must be nonempty text")
        if status not in (None, "error"):
            raise VisualReportError("Evaluator error contradicts report status")
        status = "error"
    if status is None:
        status = "assessed" if broken is not None and score is not None else "uncertain"
    if status not in ("assessed", "uncertain", "error"):
        raise VisualReportError("status must be assessed, uncertain or error")
    if status == "assessed" and (broken is None or score is None):
        raise VisualReportError("Assessed reports require broken and score assessments")
    if status != "assessed" and declared_pass is True:
        raise VisualReportError("Uncertain/error assessments cannot declare a pass")
    if status == "uncertain" and not uncertainty:
        if strict:
            raise VisualReportError("Uncertain reports require explicit uncertainty")
        uncertainty = ["The evaluator could not assess the supplied evidence"]
    if status == "error" and not error and not report.get("limits"):
        raise VisualReportError("Evaluator errors require an error message or limits")

    limits = _items(report.get("limits", report.get("limitations", score_obj.get("limits", score_obj.get("limitations", [])))), "limits")
    evidence = report.get("evidence", score_obj.get("evidence"))
    if evidence is None:
        if strict or "evidence" in report or "evidence" in score_obj:
            raise VisualReportError("evidence must be an object")
        evidence = {"kind": "ui", "sufficient": True, "observations": []}
        limits.append("Legacy report does not identify its visual evidence")
    if isinstance(evidence, list) and not strict:
        observations = _items(evidence, "score.evidence")
        evidence = {"kind": report.get("kind", report.get("evidence_kind", "ui")), "sufficient": bool(observations), "observations": observations}
    if not isinstance(evidence, dict):
        raise VisualReportError("evidence must be an object")
    if strict and not {"kind", "sufficient", "observations"}.issubset(evidence):
        raise VisualReportError("Evidence is missing kind, sufficient or observations")
    evidence = copy.deepcopy(evidence)
    kind = evidence.get("kind", report.get("kind", report.get("evidence_kind", "ui")))
    aliases = {"diff": "proxy", "text": "proxy", "image_proxy": "proxy", "proxy_structural": "proxy", "screenshots": "ui", "rendered_ui": "ui"}
    kind = aliases.get(kind, kind) if isinstance(kind, str) else None
    if kind not in ("ui", "proxy", "insufficient"):
        raise VisualReportError("Unsupported evidence kind")
    # The old diff judge synthesized a sound-page assessment. It is not UI proof.
    reasons = _items(broken_obj.get("reasons", []), "broken.reasons")
    if "diff_mode" in reasons:
        kind = "proxy"
    for marker in (report.get("kind"), report.get("evidence_kind")):
        if isinstance(marker, str) and aliases.get(marker, marker) in ("proxy", "insufficient"):
            kind = aliases.get(marker, marker)
    evidence["kind"] = kind
    evidence["sufficient"] = _boolean(evidence.get("sufficient", kind != "insufficient"), "evidence.sufficient")
    evidence["observations"] = _items(evidence.get("observations", []), "evidence.observations")

    blockers = _items(report.get("blockers", []), "blockers")
    for item in _items(score_obj.get("blockers", []), "score.blockers"):
        if item not in blockers:
            blockers.append(item)

    canonical = copy.deepcopy(report)
    canonical.update(
        schema_version=1, status=status, broken=broken, confidence=confidence, score=score,
        **{"pass": declared_pass}, blockers=blockers,
        uncertainty=uncertainty, limits=limits, evidence=evidence,
        strengths=_items(report.get("strengths", score_obj.get("strengths", score_obj.get("highlights", []))), "strengths"),
        issues=_items(report.get("issues", score_obj.get("issues", [])), "issues"),
    )
    if error is not None:
        canonical["error"] = error
    if not strict:
        canonical["legacy_assessments"] = {"broken": copy.deepcopy(broken_obj), "score": copy.deepcopy(score_obj)}
    return canonical


def visual_verdict(report: dict, threshold: float) -> tuple[bool, float | None]:
    """Fail closed on malformed evidence; use validation separately to record errors."""
    threshold_value = _number(threshold, "threshold", 10)
    try:
        quality = validate_visual_report(report)
    except VisualReportError:
        return False, None
    score = quality["score"]
    eligible = (
        quality["status"] == "assessed" and quality["broken"] is False
        and not quality["blockers"] and quality["pass"] is not False
        and quality["evidence"]["kind"] == "ui" and quality["evidence"]["sufficient"]
        and score is not None and score >= threshold_value
    )
    return bool(eligible), score


_GIT_CONFIG = [
    "-c", "core.safecrlf=false",
    "-c", "core.quotepath=true", "-c", "core.fsmonitor=false",
]
_GIT_ENV_OVERRIDES = {
    "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_PREFIX", "GIT_CONFIG_COUNT", "GIT_CEILING_DIRECTORIES",
}
_GENERATED_DIRS = {
    "node_modules", ".next", ".nuxt", ".svelte-kit", ".angular", ".parcel-cache", ".turbo",
    ".cache", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv", "venv", "__pycache__",
    "dist", "build", "coverage", ".idea", ".vscode", ".eggs", "htmlcov",
    ".vercel", ".output", ".astro", "dist-ssr", "storybook-static", "out",
}
_SECRET_DIRS = {".ssh", ".aws", ".azure", ".gnupg", ".kube"}
_SECRET_FILES = {".netrc", ".npmrc", ".pypirc", ".mcp.json", "credentials.json", "secrets.json", "id_rsa", "id_ed25519"}
_ENV_TEMPLATES = {".env.example", ".env.sample", ".env.template"}


def _git_env(**overrides: str) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key not in _GIT_ENV_OVERRIDES}
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", **overrides)
    return env


async def _git(repo: Path, args: list[str], *, env: dict[str, str] | None = None, allow_missing: bool = False, input_text: str | None = None) -> str:
    command = ["git", *_GIT_CONFIG, *args]
    if input_text is None:
        rc, out, _err = await run_argv(command, cwd=repo, env=env or _git_env(), timeout_ms=120_000)
    else:
        try:
            rc, out, _err = await run_process_argv(command, cwd=repo, env=env or _git_env(), input_text=input_text)
        except (OSError, asyncio.TimeoutError) as exc:
            raise EvidenceError(f"Git {args[0]} could not complete") from exc
    if rc != 0 and not (allow_missing and rc == 1):
        # Filter/command errors can contain private content. Do not forward stderr.
        raise EvidenceError(f"Git {args[0]} failed (exit {rc}); source evidence is unavailable")
    if "\ufffd" in out:
        # The shared process runner replaces undecodable output. A replacement
        # glyph in a diff/path could silently corrupt the delivered contents.
        raise EvidenceError("Git output contains undecodable or replacement-character text; mark non-UTF-8 files binary with Git attributes")
    return out if rc == 0 else ""


def _relative(path: str) -> str:
    if not isinstance(path, str):
        raise EvidenceError("Source paths must be strings")
    pure = PurePosixPath(path)
    if not pure.parts or pure.as_posix() != path or pure.is_absolute() or any(part in (".", "..") or part.lower() == ".git" for part in pure.parts):
        raise EvidenceError("Unsafe source path")
    if "\\" in path or "\x00" in path or re.match(r"^[A-Za-z]:", path):
        raise EvidenceError("Source path is not portable")
    return pure.as_posix()


def _sensitive(path: str) -> bool:
    # Classify every component so a sensitive directory name protects its children.
    return any(
        name in _SECRET_DIRS or name in _SECRET_FILES
        or (name.startswith(".env") and name not in _ENV_TEMPLATES)
        or name.endswith((".pem", ".key", ".p12", ".pfx"))
        or name.startswith(("service-account", "service_account", "secrets."))
        for name in (part.lower() for part in PurePosixPath(path).parts)
    )


def _generated(path: str) -> bool:
    parts = PurePosixPath(path.rstrip("/")).parts
    name = parts[-1]
    return (
        any(part in _GENERATED_DIRS or part.endswith(".egg-info") for part in parts)
        or name in (".DS_Store", "next-env.d.ts")
        or name.endswith((".pyc", ".pyo", ".log", ".swp", ".swo", ".tsbuildinfo"))
    )


def _index_entries(output: str) -> dict[str, tuple[str, str]]:
    entries: dict[str, tuple[str, str]] = {}
    for line in output.split("\x00"):
        if not line:
            continue
        metadata, path = line.split("\t", 1)
        mode, oid, stage = metadata.split()
        if stage != "0" or mode not in ("100644", "100755", "120000"):
            raise EvidenceError("Unmerged entries, submodules or unsupported Git modes cannot be snapshotted")
        entries[_relative(path)] = (mode, oid)
    return entries


async def _check_attributes(repo: Path, paths: list[str], *, env: dict[str, str] | None = None) -> None:
    for start in range(0, len(paths), 128):
        for cached in ([], ["--cached"]):
            out = await _git(repo, ["check-attr", *cached, "--all", "-z", "--", *paths[start:start + 128]], env=env)
            records = out.rstrip("\x00").split("\x00") if out else []
            for index in range(0, len(records), 3):
                attribute, value = records[index + 1:index + 3]
                if attribute == "filter" and value not in ("unset", "unspecified"):
                    raise EvidenceError(f"Git clean/smudge filters are not supported: {records[index]}")
                if attribute in ("ident", "working-tree-encoding") and value not in ("unset", "unspecified"):
                    raise EvidenceError(f"Unsupported Git checkout transformation: {records[index]}")


async def _source_state(repo: Path) -> dict:
    # Even read commands such as diff can refresh racily-clean index entries.
    # Preserve staged intent and the original index bytes with a private copy.
    index_path = Path((await _git(repo, ["rev-parse", "--git-path", "index"])).strip())
    if not index_path.is_absolute():
        index_path = repo / index_path
    with tempfile.TemporaryDirectory(prefix="frontend-design-loop-state-", dir=_temp_parent(repo)) as tmp:
        private_index = Path(tmp) / "index"
        if index_path.exists():
            # Git uses the index timestamp to detect same-size working edits
            # that share cached file timestamps. A fresh copy time hides them.
            shutil.copy2(index_path, private_index)
        return await _read_source_state(repo, _git_env(GIT_INDEX_FILE=str(private_index)))


async def _read_source_state(repo: Path, env: dict[str, str]) -> dict:
    async def _state_git(root: Path, args: list[str], **kwargs) -> str:
        return await _git(root, args, env=env, **kwargs)

    root = (await _state_git(repo, ["rev-parse", "--show-toplevel"])).rstrip("\n")
    if Path(root).resolve() != repo.resolve():
        raise EvidenceError("Expected the Git repository root, not a subdirectory")
    head = (await _state_git(repo, ["rev-parse", "--verify", "HEAD^{commit}"])).strip()
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head):
        raise EvidenceError("A repository with an existing HEAD commit is required")
    if (await _state_git(repo, ["config", "--bool", "core.sparseCheckout"], allow_missing=True)).strip() == "true":
        raise EvidenceError("Sparse checkouts cannot be snapshotted completely")
    index = _index_entries(await _state_git(repo, ["ls-files", "--stage", "-z"]))
    tree = await _state_git(repo, ["ls-tree", "-r", "-z", "HEAD"])
    base: dict[str, tuple[str, str]] = {}
    for record in tree.split("\x00"):
        if record:
            metadata, path = record.split("\t", 1)
            mode, kind, oid = metadata.split()
            if kind != "blob" or mode not in ("100644", "100755", "120000"):
                raise EvidenceError("Submodules or unsupported Git modes cannot be snapshotted")
            base[_relative(path)] = (mode, oid)
    untracked = [_relative(path) for path in (await _state_git(repo, ["ls-files", "--others", "--exclude-standard", "-z"])).split("\x00") if path]
    ignored = [path for path in (await _state_git(repo, ["ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z"])).split("\x00") if path]
    tracked = set(base) | set(index)
    excluded_sensitive = sorted(path for path in untracked if path not in tracked and _sensitive(path))
    excluded_generated = sorted(path for path in untracked if path not in tracked and not _sensitive(path) and _generated(path))
    retained_untracked = sorted(set(untracked) - set(excluded_sensitive) - set(excluded_generated))
    paths = sorted(tracked | set(retained_untracked))
    await _check_attributes(repo, paths, env=env)
    porcelain = await _state_git(repo, ["status", "--porcelain=v1", "-z", "--untracked-files=no"])
    porcelain += "".join(f"?? {path}\x00" for path in retained_untracked)
    changed = (await _state_git(repo, ["diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z", "HEAD", "--"])).split("\x00")
    if any(_sensitive(path) for path in changed if path):
        raise EvidenceError("A sensitive tracked path has changes; refusing to export it")
    # Git's assume-unchanged flag can hide a working edit from status/diff. Check
    # sensitive tracked contents against HEAD before any temporary staging occurs.
    sensitive_tracked = sorted(path for path in tracked if _sensitive(path))
    sensitive_files = _manifest(repo, sensitive_tracked, head)
    filemode = (await _state_git(repo, ["config", "--bool", "core.filemode"], allow_missing=True)).strip() != "false"
    symlinks = (await _state_git(repo, ["config", "--bool", "core.symlinks"], allow_missing=True)).strip() != "false"
    for path in sensitive_tracked:
        info = sensitive_files.get(path)
        previous = index.get(path, base.get(path))
        entry = None
        if info is not None:
            mode, oid = info["mode"], info["git_blob"]
            if info["kind"] == "file":
                if not symlinks and previous and previous[0] == "120000":
                    mode = "120000"
                else:
                    oid = (await _state_git(repo, ["hash-object", f"--path={path}", "--", str(repo / path)])).strip()
                    if not filemode and previous and previous[0] in ("100644", "100755"):
                        mode = previous[0]
            entry = (mode, oid)
        if base.get(path) != entry:
            raise EvidenceError("A sensitive tracked path has changes; refusing to export it")
    return {
        "base_head": head, "paths": paths, "index": index, "base": base,
        "checkout": {"filemode": filemode, "symlinks": symlinks},
        "status": {
            "dirty": bool(porcelain), "porcelain": porcelain, "untracked": retained_untracked,
            "excluded_ignored": sorted(ignored), "excluded_generated": excluded_generated,
            "excluded_sensitive": excluded_sensitive,
        },
        "source_policy": {
            "version": 1,
            "include": "Tracked HEAD/index paths at their working contents, plus untracked nonignored, nongenerated, nonsensitive source",
            "tracked_precedence": "Ignored/generated names never exclude tracked source; changed tracked sensitive paths fail explicitly",
            "exclusions": sorted(
                [{"path": path, "reason": "ignored"} for path in ignored]
                + [{"path": path, "reason": "generated"} for path in excluded_generated]
                + [{"path": path, "reason": "sensitive"} for path in excluded_sensitive],
                key=lambda item: (item["path"], item["reason"]),
            ),
            "limits": [
                "Ignored paths are omitted even when they contain ordinary source; exclusions record names only, never contents",
                "Generated and sensitive untracked paths are classified by name, not by reading their contents or symlink targets",
                "This policy does not scan retained source for embedded secrets; unchanged tracked sensitive paths remain part of the baseline",
            ],
        },
    }


def _manifest(repo: Path, paths: list[str], head: str) -> dict:
    files: dict[str, dict] = {}
    for path in paths:
        _relative(path)
        target = repo / path
        for parent in PurePosixPath(path).parents:
            if parent != PurePosixPath(".") and (repo / parent).is_symlink():
                raise EvidenceError("Source paths cannot traverse directory symlinks")
        try:
            metadata = target.lstat()
        except (FileNotFoundError, NotADirectoryError):
            continue
        if stat.S_ISDIR(metadata.st_mode):
            # A tracked file may have been deleted and replaced with a directory.
            # Its new children are separate untracked paths in the source manifest.
            continue
        if stat.S_ISLNK(metadata.st_mode):
            link = os.readlink(target)
            if Path(link).is_absolute() or not (target.parent / link).resolve().is_relative_to(repo.resolve()):
                raise EvidenceError(f"Source symlink escapes the candidate: {path}")
            payload = os.fsencode(link)
            mode, kind = "120000", "symlink"
        elif stat.S_ISREG(metadata.st_mode):
            payload = target.read_bytes()
            mode, kind = ("100755" if metadata.st_mode & 0o111 else "100644"), "file"
        else:
            raise EvidenceError(f"Source contains an unsupported file type: {path}")
        blob = b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload
        git_hash = hashlib.sha256(blob) if len(head) == 64 else hashlib.sha1(blob)
        files[path] = {"kind": kind, "mode": mode, "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), "git_blob": git_hash.hexdigest()}
    return files


def _fingerprint(files: dict) -> str:
    return hashlib.sha256(json.dumps(files, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()


def _temp_parent(*excluded: Path) -> Path:
    """Keep temporary indices/backups out of their own source trees, even with TMPDIR."""
    parent = Path(tempfile.gettempdir()).resolve()
    # A candidate may refer to a different source checkout. Do not create even
    # transient patch payloads in a live checkout containing the configured tempdir.
    repositories = [path for path in (parent, *parent.parents) if (path / ".git").exists()]
    while any(parent.is_relative_to(root.resolve()) for root in (*excluded, *repositories)):
        if parent == parent.parent:
            raise EvidenceError("No temporary directory exists outside the candidate/source tree")
        parent = parent.parent
    return parent


async def _set_index_entries(repo: Path, entries: dict[str, tuple[str, str]], env: dict[str, str]) -> None:
    if entries:
        records = "".join(f"{mode} {oid}\t{path}\0" for path, (mode, oid) in entries.items())
        await _git(repo, ["update-index", "-z", "--index-info"], env=env, input_text=records)


async def _export(repo: Path) -> dict:
    state = await _source_state(repo)
    files = _manifest(repo, state["paths"], state["base_head"])
    with tempfile.TemporaryDirectory(prefix="frontend-design-loop-index-", dir=_temp_parent(repo)) as tmp:
        env = _git_env(GIT_INDEX_FILE=str(Path(tmp) / "index"), GIT_LITERAL_PATHSPECS="1")
        await _git(repo, ["read-tree", state["base_head"]], env=env)
        # Never ask Git to stage the whole tree: it would read excluded untracked
        # files (including dependency symlinks). HEAD/index union preserves tracked
        # paths even after staged removal or a newly matching ignore rule.
        removed = sorted(set(state["base"]) - set(files))
        retained = sorted(files)
        for start in range(0, len(removed), 128):
            await _git(repo, ["update-index", "--force-remove", "--", *removed[start:start + 128]], env=env)
        # Seed index type/mode intent before asking Git to normalize the working
        # files. core.symlinks=false and core.filemode=false depend on this metadata.
        seed = {path: state["index"][path] for path in retained if path in state["index"]}
        await _set_index_entries(repo, seed, env)
        for start in range(0, len(retained), 128):
            await _git(repo, ["add", "--force", "--all", "--", *retained[start:start + 128]], env=env)
        staged = _index_entries(await _git(repo, ["ls-files", "--stage", "-z"], env=env))
        if set(staged) != set(files):
            raise EvidenceError("Git staging did not retain the complete source manifest")
        git_files = {path: {"mode": mode, "git_blob": oid} for path, (mode, oid) in staged.items()}
        # The delivered patch represents physical bytes/types, rather than Git's
        # cleaned blobs. No filters or text conversion run while hashing these.
        for start in range(0, len(retained), 128):
            batch = retained[start:start + 128]
            payload_paths = []
            for path in batch:
                info = files[path]
                with tempfile.NamedTemporaryFile(dir=tmp, delete=False) as handle:
                    payload_paths.append(Path(handle.name))
                    payload = os.fsencode(os.readlink(repo / path)) if info["kind"] == "symlink" else (repo / path).read_bytes()
                    handle.write(payload)
            oids = (await _git(repo, ["hash-object", "-w", "--no-filters", "--", *map(str, payload_paths)], env=env)).splitlines()
            if len(oids) != len(batch):
                raise EvidenceError("Git did not hash the complete physical source")
            entries = {}
            for path, oid, payload_path in zip(batch, oids, payload_paths):
                payload_path.unlink()
                info = files[path]
                if oid != info["git_blob"]:
                    raise EvidenceError("Source changed while capturing physical blobs")
                mode = info["mode"]
                # Windows cannot expose POSIX executable permissions. Preserve
                # Git's executable intent and fingerprint the observed mode.
                if os.name == "nt" and mode == "100644" and staged[path][0] == "100755":
                    mode = "100755"
                entries[path] = (mode, oid)
            await _set_index_entries(repo, entries, env)
        patch = await _git(repo, ["diff", "--cached", "--binary", "--full-index", "--no-ext-diff", "--no-textconv", "--no-renames", "--no-color", "--src-prefix=a/", "--dst-prefix=b/", state["base_head"], "--"], env=env)
    after = await _source_state(repo)
    if after != state or _manifest(repo, after["paths"], after["base_head"]) != files:
        raise EvidenceError("Source changed while capturing evidence; retry when the working tree is stable")
    return {"base_head": state["base_head"], "patch": patch, "fingerprint": _fingerprint(files), "files": files, "source_status": state["status"], "source_policy": state["source_policy"], "git_files": git_files, "patch_representation": "physical-checkout-v1"}


async def export_patch(repo_root: Path) -> str:
    """HEAD-to-retained-working-source delta under the snapshot inclusion policy."""
    return (await _export(Path(repo_root).resolve()))["patch"]


async def source_snapshot(repo_root: Path) -> dict:
    """Bind dirty source contents and explicit exclusions to a replayable delta."""
    return await _export(Path(repo_root).resolve())


class CandidateCheckpoint:
    """Disk checkpoint for detached linked worktrees or explicitly isolated dirs.

    Plain directories without Git metadata are accepted for injected/test candidates.
    Standalone repositories require isolated=True. All filesystem contents, including
    ignored files, are captured; .git is protected and the candidate index is saved.
    capture/restore are async to match orchestration, but filesystem recovery does not
    suspend, so cancellation cannot interrupt it or race a background copy operation.
    """

    def __init__(self, candidate: Path, *, isolated: bool = False):
        self.candidate = Path(candidate).resolve()
        self.isolated = isolated
        self._backup: Path | None = None
        self._index: Path | None = None
        self._index_bytes: bytes | None = None
        self._index_mode: int | None = None
        self._keep_backup = False

    def _guard(self) -> None:
        if not self.candidate.is_dir():
            raise EvidenceError("Candidate directory does not exist")
        marker = self.candidate / ".git"
        if marker.is_symlink():
            raise EvidenceError("Candidate Git metadata cannot be a symlink")
        if marker.is_file():
            text = marker.read_text(encoding="utf-8").strip()
            if not text.startswith("gitdir: "):
                raise EvidenceError("Unsupported candidate Git metadata")
            gitdir = Path(text[8:])
            gitdir = (self.candidate / gitdir).resolve() if not gitdir.is_absolute() else gitdir.resolve()
            # A submodule .git file is not an isolated linked worktree.
            if not (gitdir / "commondir").is_file():
                raise EvidenceError("Only isolated linked worktrees may use external Git metadata")
            if not self.isolated and (gitdir / "HEAD").read_text().startswith("ref:"):
                raise EvidenceError("Candidate worktree must be detached")
            self._index = gitdir / "index"
        elif marker.is_dir():
            if not self.isolated:
                raise EvidenceError("Refusing to checkpoint a live repository; use an isolated candidate")
            self._index = marker / "index"
        for current, dirs, names in os.walk(self.candidate, followlinks=False):
            if Path(current) == self.candidate:
                dirs[:] = [name for name in dirs if name != ".git"]
                names = [name for name in names if name != ".git"]
            elif ".git" in dirs or ".git" in names:
                raise EvidenceError("Nested repositories cannot be checkpointed safely")
            for name in dirs + names:
                mode = (Path(current) / name).lstat().st_mode
                if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode) or stat.S_ISLNK(mode)):
                    raise EvidenceError("Candidate contains special files that cannot be checkpointed")

    async def capture(self) -> CandidateCheckpoint:
        self._guard()
        backup = Path(tempfile.mkdtemp(prefix="frontend-design-loop-checkpoint-", dir=_temp_parent(self.candidate)))
        try:
            shutil.copytree(self.candidate, backup / "contents", symlinks=True, ignore=lambda path, names: [".git"] if Path(path) == self.candidate else [])
            index_bytes = self._index.read_bytes() if self._index and self._index.exists() else None
            index_mode = stat.S_IMODE(self._index.stat().st_mode) if self._index and self._index.exists() else None
        except BaseException:
            _remove_tree(backup)
            raise
        self.close()
        self._backup, self._index_bytes, self._index_mode = backup, index_bytes, index_mode
        return self

    async def restore(self) -> None:
        if self._backup is None:
            raise EvidenceError("Checkpoint has not been captured")
        self._keep_backup = True
        try:
            if self.candidate.is_symlink() or not self.candidate.is_dir():
                raise EvidenceError("Candidate directory was replaced; refusing to follow it during rollback")
            self.candidate.chmod(self.candidate.stat().st_mode | stat.S_IWUSR | stat.S_IXUSR)
            for entry in self.candidate.iterdir():
                if entry.name == ".git":
                    continue
                if entry.is_dir() and not entry.is_symlink():
                    _remove_tree(entry)
                else:
                    try:
                        entry.unlink()
                    except PermissionError:
                        if entry.is_symlink():
                            raise
                        entry.chmod(entry.stat().st_mode | stat.S_IWUSR)
                        entry.unlink()
            shutil.copytree(self._backup / "contents", self.candidate, dirs_exist_ok=True, symlinks=True)
            if self._index is not None:
                if self._index_bytes is None:
                    self._index.unlink(missing_ok=True)
                else:
                    _atomic_bytes(self._index, self._index_bytes)
                    if self._index_mode is not None:
                        self._index.chmod(self._index_mode)
            self._keep_backup = False
        except BaseException as exc:
            raise EvidenceError(f"Candidate rollback failed; recovery checkpoint retained at {self._backup}") from exc

    def close(self) -> None:
        if self._backup is not None and not self._keep_backup:
            _remove_tree(self._backup)
            self._backup = None

    async def __aenter__(self) -> CandidateCheckpoint:
        return await self.capture()

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        try:
            if exc_type is not None:
                await self.restore()
        finally:
            self.close()


def _remove_tree(path: Path) -> None:
    def retry_readonly(operation: Callable, target: str, exc_info: tuple) -> None:
        entry = Path(target)
        if not isinstance(exc_info[1], PermissionError) or entry.is_symlink():
            raise exc_info[1]
        entry.chmod(entry.stat().st_mode | stat.S_IWUSR | stat.S_IXUSR)
        operation(target)

    # onerror is supported on Python 3.10 and handles Windows read-only files.
    shutil.rmtree(path, onerror=retry_readonly)


def _atomic_bytes(path: Path, payload: bytes) -> None:
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(payload)
            handle.flush()
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


async def apply_patch_transaction(repo_root: Path, patches: list, apply_fn: Callable, *, isolated: bool = False) -> tuple[bool, list[str]]:
    """Apply one complete bundle; restore on failure and re-raise exceptions/cancellation."""
    if not isinstance(patches, list):
        raise EvidenceError("A patch transaction requires a list of patches")
    for patch in patches:
        if isinstance(patch, dict) and isinstance(patch.get("path"), str):
            parts = PurePosixPath(patch["path"].strip().replace("\\", "/")).parts
            if any(part.rstrip(". ").lower() == ".git" or part.lower().startswith(".git:") for part in parts):
                return False, []
    checkpoint = CandidateCheckpoint(repo_root, isolated=isolated)
    await checkpoint.capture()
    try:
        result = apply_fn(repo_root=repo_root, patches=patches)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, tuple) or len(result) != 2 or type(result[0]) is not bool or not isinstance(result[1], list) or any(not isinstance(path, str) for path in result[1]):
            raise EvidenceError("Patch application returned an invalid transaction result")
        if not result[0]:
            await checkpoint.restore()
            return False, []
        return result
    except BaseException:
        await checkpoint.restore()
        raise
    finally:
        checkpoint.close()


async def _materialize_index(repo: Path, tree: Path, env: dict[str, str], *, removed: set[str] | None = None) -> None:
    """Read raw blobs, never checkout/smudge them, into an isolated replay tree."""
    entries = _index_entries(await _git(repo, ["ls-files", "--stage", "-z"], env=env))
    paths = sorted(entries)
    # cat-file's binary batch protocol preserves even non-UTF-8 binary blobs.
    # This command cannot invoke filters, hooks or a shell; bound and reap it on
    # timeout/cancellation just like the shared text command runner.
    proc = await launch_process_argv(
        ["git", *_GIT_CONFIG, "cat-file", "--batch"], cwd=repo, env=env,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        start_new_session=(os.name == "posix"),
    )
    try:
        output, _ = await asyncio.wait_for(proc.communicate("".join(f"{entries[path][1]}\n" for path in paths).encode("ascii")), 120)
        if proc.returncode:
            raise EvidenceError("Git blob replay failed")
    except (OSError, asyncio.TimeoutError) as exc:
        raise EvidenceError("Git blob replay could not complete") from exc
    finally:
        await terminate_process_tree(proc, drain_output=True)
    for path in sorted(removed or set(), reverse=True):
        target = tree / _relative(path)
        _guard_parents(tree, path)
        if target.is_symlink() or target.is_file():
            target.unlink()
            # File/directory transitions need empty former tracked directories
            # removed; keep any directory containing ignored or unrelated files.
            parent = target.parent
            while parent != tree:
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
    offset = 0
    for path in paths:
        mode, oid = entries[path]
        end = output.index(b"\n", offset)
        blob_oid, kind, size = output[offset:end].split()
        length = int(size)
        offset = end + 1
        payload = output[offset:offset + length]
        if blob_oid.decode("ascii") != oid or kind != b"blob" or len(payload) != length or output[offset + length:offset + length + 1] != b"\n":
            raise EvidenceError("Git blob replay returned invalid contents")
        offset += length + 1
        _guard_parents(tree, path)
        target = tree / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            target.unlink()
        if mode == "120000":
            link = os.fsdecode(payload)
            if Path(link).is_absolute() or not (target.parent / link).resolve().is_relative_to(tree.resolve()):
                raise EvidenceError(f"Source symlink escapes the candidate: {path}")
            if target.exists():
                target.unlink()
            target.symlink_to(link)
        else:
            _atomic_bytes(target, payload)
            target.chmod(0o755 if mode == "100755" else 0o644)
    if offset != len(output):
        raise EvidenceError("Git blob replay returned excess contents")


def _guard_parents(tree: Path, path: str) -> None:
    for parent in PurePosixPath(path).parents:
        if parent != PurePosixPath(".") and (tree / parent).is_symlink():
            raise EvidenceError("Source paths cannot traverse directory symlinks")


async def _patch_index(repo: Path, patch: str, directory: Path, env: dict[str, str]) -> None:
    if not isinstance(patch, str):
        raise EvidenceError("Exported patch must be text")
    if patch:
        path = directory / "changes.patch"
        path.write_bytes(patch.encode("utf-8"))
        await _git(repo, ["apply", "--cached", "--binary", "--whitespace=nowarn", "--", str(path)], env=env)


async def apply_source_snapshot(worktree: Path, snapshot: dict) -> None:
    """Overlay a validated source snapshot on a pristine, matching candidate HEAD."""
    worktree = Path(worktree).resolve()
    if not isinstance(snapshot, dict) or not {"base_head", "patch", "fingerprint", "files"}.issubset(snapshot):
        raise EvidenceError("Source snapshot is missing replay evidence")
    if not isinstance(snapshot["files"], dict) or _fingerprint(snapshot["files"]) != snapshot["fingerprint"]:
        raise EvidenceError("Source snapshot fingerprint is invalid")
    for path in snapshot["files"]:
        _relative(path)
    state = await _source_state(worktree)
    if state["base_head"] != snapshot["base_head"] or state["status"]["dirty"]:
        raise EvidenceError("Source overlay requires a pristine candidate at the snapshot HEAD")
    async with CandidateCheckpoint(worktree):
        with tempfile.TemporaryDirectory(prefix="frontend-design-loop-overlay-", dir=_temp_parent(worktree)) as tmp:
            directory = Path(tmp)
            env = _git_env(GIT_INDEX_FILE=str(directory / "index"))
            await _git(worktree, ["read-tree", snapshot["base_head"]], env=env)
            await _patch_index(worktree, snapshot["patch"], directory, env)
            await _materialize_index(worktree, worktree, env, removed=set(state["base"]) - set(snapshot["files"]))
        current = await _source_state(worktree)
        files = _manifest(worktree, current["paths"], current["base_head"])
        if files != snapshot["files"] or _fingerprint(files) != snapshot["fingerprint"]:
            raise EvidenceError("Source replay did not reproduce the supplied working contents")


def _tree_paths(root: Path) -> list[str]:
    paths: list[str] = []
    for current, dirs, names in os.walk(root, followlinks=False):
        for name in list(dirs):
            if (Path(current) / name).is_symlink():
                names.append(name)
                dirs.remove(name)
        paths.extend((Path(current) / name).relative_to(root).as_posix() for name in names)
    return sorted(paths)


async def verify_patch_delivery(base_repo: Path, base_head: str, patch: str, candidate: Path) -> dict:
    """Replay into a disposable filesystem with a temporary index, creating no refs."""
    result: dict = {"ok": False, "base_head": base_head, "expected_fingerprint": None, "replay_fingerprint": None, "mismatches": []}
    try:
        if not isinstance(base_head, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", base_head):
            raise EvidenceError("Delivery base must be an exact commit ID")
        state = await _source_state(Path(candidate).resolve())
        if state["base_head"] != base_head:
            raise EvidenceError("Candidate HEAD does not match the recorded delivery base")
        expected = _manifest(Path(candidate).resolve(), state["paths"], base_head)
        result["expected_fingerprint"] = _fingerprint(expected)
        with tempfile.TemporaryDirectory(prefix="frontend-design-loop-replay-", dir=_temp_parent(Path(base_repo), Path(candidate))) as tmp:
            tree = Path(tmp) / "tree"
            tree.mkdir()
            env = _git_env(GIT_INDEX_FILE=str(Path(tmp) / "index"), GIT_WORK_TREE=str(tree))
            await _git(Path(base_repo).resolve(), ["read-tree", base_head], env=env)
            index = _index_entries(await _git(Path(base_repo).resolve(), ["ls-files", "--stage", "-z"], env=env))
            await _check_attributes(Path(base_repo).resolve(), sorted(index), env=env)
            await _patch_index(Path(base_repo).resolve(), patch, Path(tmp), env)
            await _materialize_index(Path(base_repo).resolve(), tree, env)
            replay = _manifest(tree, _tree_paths(tree), base_head)
            result["replay_fingerprint"] = _fingerprint(replay)
            result["mismatches"] = sorted(path for path in set(expected) | set(replay) if expected.get(path) != replay.get(path))
            after = await _source_state(Path(candidate).resolve())
            if after != state or _manifest(Path(candidate).resolve(), after["paths"], base_head) != expected:
                raise EvidenceError("Candidate changed during delivery verification")
            result["ok"] = not result["mismatches"]
    except (EvidenceError, OSError, ValueError) as exc:
        result["error"] = str(exc)
    return result
