"""Real source-policy artifacts retain source, exclude private/build data, and replay exactly."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from frontend_design_loop_core import evidence


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True).stdout.decode()


def commit(repo: Path) -> None:
    git(repo, "add", "--force", ".")
    git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    root.mkdir()
    git(root, "init", "-q")
    (root / "app.tsx").write_bytes(b"export default 'original';\n")
    (root / ".gitignore").write_text(".env.local\nignored-source/\n")
    commit(root)
    return root


@pytest.fixture
def candidate(repo: Path, tmp_path: Path):
    root = tmp_path / "candidate"
    git(repo, "worktree", "add", "--detach", str(root), "HEAD")
    yield root
    git(repo, "worktree", "remove", "--force", str(root))


@pytest.mark.asyncio
async def test_next_vite_policy_artifacts_and_exact_retained_replay(repo, candidate, tmp_path, monkeypatch):
    excluded = {
        ".env.local": b"IGNORED_PRIVATE_SENTINEL=secret\xff\n",
        ".env.production": b"UNTRACKED_PRIVATE_SENTINEL=secret\n",
        "ignored-source/important.ts": b"IGNORED_SOURCE_SENTINEL\n",
        "next-env.d.ts": b"GENERATED_NEXT_SENTINEL\n",
        "tsconfig.tsbuildinfo": b"GENERATED_TYPESCRIPT_SENTINEL\n",
        "node_modules/package/index.js": b"DEPENDENCY_SENTINEL\n",
        ".aws/credentials": b"AWS_PRIVATE_SENTINEL\n",
    }
    for path, payload in excluded.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    (repo / "app.tsx").write_bytes(b"export default 'staged';\n")
    git(repo, "add", "app.tsx")
    retained = {
        "app.tsx": b"export default 'working';\n",
        "src/new [route].tsx": b"export const route = 'new';\n",
        ".env.example": b"PUBLIC_ORIGIN=https://example.invalid\n",
        "assets/new.dat": b"new\x00binary\xff",
    }
    for path, payload in retained.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    index_before = (repo / ".git" / "index").read_bytes()
    refs_before = git(repo, "show-ref")
    original_read = Path.read_bytes
    original_manifest = evidence._manifest
    original_git = evidence._git
    staged_paths = set()

    def guarded_read(path):
        assert path not in {repo / name for name in excluded}, "Excluded source contents must never be opened"
        return original_read(path)

    def guarded_manifest(root, paths, head):
        assert not set(paths).intersection(excluded), "Exclusions must happen before manifest traversal"
        return original_manifest(root, paths, head)

    async def guarded_git(root, args, **kwargs):
        if args[0] == "add":
            paths = args[args.index("--") + 1:]
            assert "." not in paths
            assert not set(paths).intersection(excluded)
            staged_paths.update(paths)
        return await original_git(root, args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", guarded_read)
    monkeypatch.setattr(evidence, "_manifest", guarded_manifest)
    monkeypatch.setattr(evidence, "_git", guarded_git)
    snapshot = await evidence.source_snapshot(repo)
    assert await evidence.export_patch(repo) == snapshot["patch"]
    assert set(snapshot["files"]) == set(retained) | {".gitignore"}
    assert staged_paths == set(snapshot["files"])
    exclusions = {item["path"]: item["reason"] for item in snapshot["source_policy"]["exclusions"]}
    assert exclusions[".env.local"] == "ignored"
    assert exclusions["ignored-source/"] == "ignored"
    assert exclusions[".env.production"] == "sensitive"
    assert exclusions[".aws/credentials"] == "sensitive"
    assert exclusions["next-env.d.ts"] == "generated"
    assert snapshot["source_policy"]["version"] == 1
    assert snapshot["source_policy"]["limits"]
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "snapshot.json").write_text(json.dumps(snapshot, sort_keys=True))
    (artifacts / "source.patch").write_text(snapshot["patch"])
    for artifact in artifacts.iterdir():
        assert b"SENTINEL" not in artifact.read_bytes()
    await evidence.apply_source_snapshot(candidate, snapshot)
    for path, payload in retained.items():
        assert (candidate / path).read_bytes() == payload
    for path in excluded:
        assert not (candidate / path).exists()
    replay = await evidence.verify_patch_delivery(repo, snapshot["base_head"], snapshot["patch"], candidate)
    assert replay["ok"], replay
    assert replay["replay_fingerprint"] == snapshot["fingerprint"]
    assert (repo / ".git" / "index").read_bytes() == index_before
    assert git(repo, "show-ref") == refs_before


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    ".vercel/output/functions/index.js", ".output/server/index.js", ".astro/types.d.ts",
    "dist-ssr/index.js", "storybook-static/index.html", "out/index.html",
    "next-env.d.ts", "tsconfig.tsbuildinfo", "packages/web/next-env.d.ts",
    "packages/web/cache.tsbuildinfo", "node_modules/library/index.js",
])
async def test_untracked_generated_names_are_excluded_but_tracked_contents_are_retained(repo, path):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"generated output must be omitted\n")
    snapshot = await evidence.source_snapshot(repo)
    assert path not in snapshot["files"]
    assert {"path": path, "reason": "generated"} in snapshot["source_policy"]["exclusions"]
    assert snapshot["patch"] == ""
    assert not snapshot["source_status"]["dirty"]
    commit(repo)
    target.write_bytes(b"tracked ordinary contents must be retained\n")
    snapshot = await evidence.source_snapshot(repo)
    assert path in snapshot["files"]
    assert path in snapshot["patch"]
    assert "tracked ordinary contents must be retained" in snapshot["patch"]
    assert {"path": path, "reason": "generated"} not in snapshot["source_policy"]["exclusions"]
    replay = await evidence.verify_patch_delivery(repo, snapshot["base_head"], snapshot["patch"], repo)
    assert replay["ok"], replay


@pytest.mark.asyncio
@pytest.mark.skipif(os.name == "nt", reason="POSIX absolute dependency directory symlink")
@pytest.mark.parametrize("ignored", [False, True])
async def test_absolute_dependency_symlink_is_excluded_without_reading_target(repo, candidate, tmp_path, monkeypatch, ignored):
    if ignored:
        # Local info/exclude also applies to the linked candidate without changing HEAD.
        (repo / ".git" / "info" / "exclude").write_text("node_modules\n")
    external = tmp_path / "reused dependencies"
    external.mkdir()
    (external / "private.js").write_bytes(b"EXTERNAL_DEPENDENCY_SENTINEL")
    for root in (repo, candidate):
        (root / "node_modules").symlink_to(external, target_is_directory=True)
    readlink = os.readlink

    def guarded_readlink(path, *args, **kwargs):
        assert Path(path) != repo / "node_modules"
        return readlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "readlink", guarded_readlink)
    (repo / "app.tsx").write_bytes(b"export default 'updated';\n")
    snapshot = await evidence.source_snapshot(repo)
    assert "node_modules" not in snapshot["files"]
    assert "EXTERNAL_DEPENDENCY_SENTINEL" not in json.dumps(snapshot)
    reason = "ignored" if ignored else "generated"
    assert {"path": "node_modules", "reason": reason} in snapshot["source_policy"]["exclusions"]
    # A reused dependency directory does not make the retained candidate source dirty.
    assert not (await evidence.source_snapshot(candidate))["source_status"]["dirty"]
    await evidence.apply_source_snapshot(candidate, snapshot)
    assert (candidate / "app.tsx").read_bytes() == (repo / "app.tsx").read_bytes()
    replay = await evidence.verify_patch_delivery(repo, snapshot["base_head"], snapshot["patch"], candidate)
    assert replay["ok"], replay


@pytest.mark.asyncio
async def test_tracked_ignored_source_and_staged_removal_are_never_silently_omitted(repo):
    target = repo / "ignored-source" / "app.css"
    target.parent.mkdir()
    target.write_text("tracked original\n")
    commit(repo)
    git(repo, "rm", "--cached", "ignored-source/app.css")
    target.write_text("retained working version despite staged removal\n")
    (target.parent / "local.css").write_text("UNTRACKED_IGNORED_SENTINEL\n")
    index_before = (repo / ".git" / "index").read_bytes()
    snapshot = await evidence.source_snapshot(repo)
    assert "ignored-source/app.css" in snapshot["files"]
    assert "ignored-source/local.css" not in snapshot["files"]
    assert "retained working version despite staged removal" in snapshot["patch"]
    assert "UNTRACKED_IGNORED_SENTINEL" not in json.dumps(snapshot)
    replay = await evidence.verify_patch_delivery(repo, snapshot["base_head"], snapshot["patch"], repo)
    assert replay["ok"], replay
    assert (repo / ".git" / "index").read_bytes() == index_before


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["working", "staged", "deleted", "assume-unchanged"])
async def test_changed_tracked_sensitive_paths_still_fail_without_private_artifacts(repo, change):
    target = repo / ".env.local"
    target.write_text("ORIGINAL_PRIVATE_SENTINEL\n")
    commit(repo)
    if change == "assume-unchanged":
        git(repo, "update-index", "--assume-unchanged", ".env.local")
    if change == "deleted":
        target.unlink()
    else:
        target.write_text("NEW_PRIVATE_SENTINEL\n")
        if change == "staged":
            git(repo, "add", "--force", ".env.local")
    index_before = (repo / ".git" / "index").read_bytes()
    for capture in (evidence.source_snapshot, evidence.export_patch):
        with pytest.raises(evidence.EvidenceError, match="sensitive tracked") as error:
            await capture(repo)
        assert "PRIVATE_SENTINEL" not in str(error.value)
    assert (repo / ".git" / "index").read_bytes() == index_before


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [".env", ".env.development", ".env.production/token", "credentials.json", "private.key"])
async def test_sensitive_untracked_names_are_excluded_before_content_reads(repo, path, monkeypatch):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"PRIVATE_SENTINEL\x00\xff")
    original_read = Path.read_bytes

    def guarded_read(current):
        assert current != target
        return original_read(current)

    monkeypatch.setattr(Path, "read_bytes", guarded_read)
    snapshot = await evidence.source_snapshot(repo)
    assert snapshot["patch"] == ""
    assert path not in snapshot["files"]
    assert {"path": path, "reason": "sensitive"} in snapshot["source_policy"]["exclusions"]
    assert "PRIVATE_SENTINEL" not in json.dumps(snapshot)


@pytest.mark.asyncio
async def test_excluded_content_changes_do_not_change_retained_fingerprint_or_patch(repo):
    (repo / ".env.local").write_text("private original\n")
    first = await evidence.source_snapshot(repo)
    (repo / ".env.local").write_bytes(b"private replacement\x00\xff")
    second = await evidence.source_snapshot(repo)
    assert second == first


@pytest.mark.asyncio
async def test_sparse_and_submodule_protections_remain_explicit(repo):
    git(repo, "config", "core.sparseCheckout", "true")
    with pytest.raises(evidence.EvidenceError, match="Sparse"):
        await evidence.source_snapshot(repo)
    git(repo, "config", "core.sparseCheckout", "false")
    head = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{head},node_modules/vendor")
    with pytest.raises(evidence.EvidenceError, match="submodules"):
        await evidence.source_snapshot(repo)
