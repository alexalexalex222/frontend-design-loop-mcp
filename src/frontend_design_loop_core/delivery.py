"""Deliver retained source relative to a dirty baseline and replay it without hooks."""

from __future__ import annotations

import tempfile
from pathlib import Path

from .evidence import _git as evidence_git
from .evidence import _git_env, _temp_parent, source_snapshot, verify_patch_delivery

_DIFF = [
    "diff",
    "--cached",
    "--binary",
    "--full-index",
    "--no-ext-diff",
    "--no-textconv",
    "--no-color",
    "--no-renames",
    "--src-prefix=a/",
    "--dst-prefix=b/",
]


async def _git(root: Path, *args: str, env=None) -> str:
    return await evidence_git(root, list(args), env=env)


async def _apply_index(root: Path, directory: Path, patch: str, name: str, env: dict) -> None:
    if patch.strip():
        path = directory / name
        path.write_bytes(patch.encode("utf-8"))
        await _git(root, "apply", "--cached", "--binary", "--whitespace=nowarn", str(path), env=env)


async def export_candidate_delta(candidate: Path, source: dict) -> str:
    snapshot = await source_snapshot(candidate)
    if snapshot["base_head"] != source["base_head"]:
        raise ValueError(
            "Native editor changed candidate HEAD; delivery requires the recorded base"
        )
    if not source.get("patch"):
        return snapshot["patch"]
    with tempfile.TemporaryDirectory(
        prefix="frontend-loop-delta-", dir=_temp_parent(candidate)
    ) as directory:
        root = Path(directory)
        env = _git_env(GIT_INDEX_FILE=str(root / "index"))
        await _git(candidate, "read-tree", source["base_head"], env=env)
        await _apply_index(candidate, root, source["patch"], "baseline.patch", env)
        base_tree = (await _git(candidate, "write-tree", env=env)).strip()
        # Stage only the already validated retained-source patch. Whole-tree staging
        # would read excluded secrets, generated outputs or dependency symlinks.
        await _git(candidate, "read-tree", source["base_head"], env=env)
        await _apply_index(candidate, root, snapshot["patch"], "candidate.patch", env)
        return await _git(candidate, *_DIFF, base_tree, "--", env=env)


async def verify_candidate_delta(
    base_repo: Path, source: dict, patch: str, candidate: Path
) -> dict:
    try:
        with tempfile.TemporaryDirectory(
            prefix="frontend-loop-compose-", dir=_temp_parent(candidate, base_repo)
        ) as directory:
            root = Path(directory)
            env = _git_env(GIT_INDEX_FILE=str(root / "index"))
            await _git(base_repo, "read-tree", source["base_head"], env=env)
            await _apply_index(base_repo, root, source.get("patch", ""), "baseline.patch", env)
            await _apply_index(base_repo, root, patch, "delta.patch", env)
            complete = await _git(base_repo, *_DIFF, source["base_head"], "--", env=env)
        result = await verify_patch_delivery(base_repo, source["base_head"], complete, candidate)
        result["source_fingerprint"] = source["fingerprint"]
        result["candidate_fingerprint"] = result.get("expected_fingerprint")
        return result
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
