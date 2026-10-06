"""Exact physical checkout replay, independent of Git's normalized representation."""

import asyncio
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from frontend_design_loop_core import delivery, evidence, mcp_code_server


def git(root, *args, input=None):
    return subprocess.run(["git", *args], cwd=root, input=input, capture_output=True, check=True).stdout


def physical(root):
    result = {}
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if name != ".git"]
        for name in names:
            path = Path(directory) / name
            if name == ".git":
                continue
            result[path.relative_to(root).as_posix()] = (
                "symlink" if path.is_symlink() else "file",
                os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes(),
                bool(path.lstat().st_mode & 0o111) if not path.is_symlink() else False,
            )
    return result


@pytest.fixture
def repository(tmp_path, monkeypatch):
    for name in list(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_OPTIONAL_LOCKS", "0")
    root = tmp_path / "source"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "core.autocrlf", "false")
    for name, payload in {
        "page.txt": b"committed\n", "unchanged.txt": b"unchanged\n",
        "delete.txt": b"delete\n", "binary.dat": b"old\0\xff",
        "run.sh": b"#!/bin/sh\necho old\n", "unchanged.sh": b"#!/bin/sh\necho unchanged\n",
        ".env.local": b"unchanged private fixture\n",
    }.items():
        (root / name).write_bytes(payload)
    git(root, "add", ".")
    git(root, "update-index", "--chmod=+x", "run.sh", "unchanged.sh")
    if os.name != "nt":
        for name in ("run.sh", "unchanged.sh"):
            (root / name).chmod(0o755)
    git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")
    return root


@pytest.mark.asyncio
@pytest.mark.parametrize("attributes,autocrlf,eol", [
    ("*.txt text\n.env.local text\n", "true", "native"),
    ("*.txt text eol=crlf\n.env.local text eol=crlf\n", "false", "crlf"),
    ("*.txt text eol=lf\n.env.local text eol=lf\n", "input", "lf"),
    ("", "true", "crlf"),
])
async def test_crlf_source_overlay_and_dirty_baseline_delivery(repository, tmp_path, attributes, autocrlf, eol):
    root = repository
    (root / ".gitattributes").write_bytes(attributes.encode())
    git(root, "add", ".gitattributes")
    git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "attributes")
    git(root, "config", "core.autocrlf", autocrlf)
    git(root, "config", "core.eol", eol)
    for name in ("unchanged.txt", ".env.local"):
        (root / name).write_bytes((root / name).read_bytes().replace(b"\n", b"\r\n"))
    (root / "page.txt").write_bytes(b"staged\r\n")
    git(root, "add", "page.txt")
    (root / "page.txt").write_bytes(b"working\r\n")
    (root / "new.txt").write_bytes(b"new\r\n")
    (root / "delete.txt").unlink()
    (root / "binary.dat").write_bytes(b"changed\0\xfe\r\n")
    (root / "run.sh").write_bytes(b"#!/bin/sh\necho changed\n")
    (root / ".env.production").write_bytes(b"EXCLUDED_FIXTURE")
    before = (root / ".git/index").read_bytes(), git(root, "diff", "--cached", "--binary"), git(root, "config", "--local", "--list")
    candidate = tmp_path / "candidate"
    git(root, "worktree", "add", "--detach", str(candidate), "HEAD")
    candidate_index = git(candidate, "rev-parse", "--git-path", "index").decode().strip()
    candidate_index = Path(candidate_index)
    if not candidate_index.is_absolute():
        candidate_index = candidate / candidate_index
    candidate_index_before = candidate_index.read_bytes()
    source = await evidence.source_snapshot(root)
    assert source["files"]["unchanged.txt"]["sha256"] == hashlib.sha256(b"unchanged\r\n").hexdigest()
    assert source["git_files"]["unchanged.txt"]["git_blob"] != source["files"]["unchanged.txt"]["git_blob"]
    assert source["git_files"]["unchanged.sh"]["mode"] == "100755"
    assert source["git_files"]["run.sh"]["mode"] == "100755"
    assert "EXCLUDED_FIXTURE" not in source["patch"]
    await evidence.apply_source_snapshot(candidate, source)
    assert physical(candidate) == {name: value for name, value in physical(root).items() if name != ".env.production"}
    assert (await evidence.source_snapshot(candidate))["fingerprint"] == source["fingerprint"]
    assert (await evidence.verify_patch_delivery(root, source["base_head"], source["patch"], candidate))["ok"]
    assert await delivery.export_candidate_delta(candidate, source) == ""
    (candidate / "page.txt").write_bytes(b"candidate\r\n")
    (candidate / "candidate.txt").write_bytes(b"added\r\n")
    delta = await delivery.export_candidate_delta(candidate, source)
    result = await delivery.verify_candidate_delta(root, source, delta, candidate)
    assert result["ok"], result
    independent = tmp_path / "independent replay"
    git(root, "worktree", "add", "--detach", str(independent), "HEAD")
    await evidence.apply_source_snapshot(independent, source)
    patch_file = tmp_path / "delta.patch"
    saved_delta = mcp_code_server._write_patch(patch_file, delta)
    assert saved_delta == delta
    assert patch_file.read_bytes() == delta.encode("utf-8")
    git(independent, "apply", "--binary", str(patch_file))
    assert physical(independent) == physical(candidate)
    assert candidate_index.read_bytes() == candidate_index_before
    incomplete = await delivery.verify_candidate_delta(root, source, "", candidate)
    assert not incomplete["ok"]
    assert "page.txt" in incomplete["mismatches"]
    assert before == ((root / ".git/index").read_bytes(), git(root, "diff", "--cached", "--binary"), git(root, "config", "--local", "--list"))


@pytest.mark.asyncio
@pytest.mark.parametrize("modified", [False, True])
async def test_symlink_disabled_regular_target_files_replay(repository, tmp_path, modified):
    root = repository
    oid = git(root, "hash-object", "-w", "--stdin", input=b"page.txt").decode().strip()
    git(root, "update-index", "--add", "--cacheinfo", f"120000,{oid},page-link")
    git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "tracked symlink")
    git(root, "config", "core.symlinks", "false")
    git(root, "checkout-index", "--force", "--", "page-link")
    assert not (root / "page-link").is_symlink()
    if modified:
        (root / "page-link").write_bytes(b"unchanged.txt")
    candidate = tmp_path / "candidate"
    git(root, "worktree", "add", "--detach", str(candidate), "HEAD")
    before = (root / ".git/index").read_bytes()
    source = await evidence.source_snapshot(root)
    assert (root / ".git/index").read_bytes() == before, "index changed during source snapshot"
    assert source["files"]["page-link"]["kind"] == "file"
    assert source["git_files"]["page-link"]["mode"] == "120000"
    await evidence.apply_source_snapshot(candidate, source)
    assert physical(candidate) == physical(root)
    assert (await evidence.verify_patch_delivery(root, source["base_head"], source["patch"], candidate))["ok"]
    (candidate / "page-link").write_bytes(b"run.sh")
    delta = await delivery.export_candidate_delta(candidate, source)
    result = await delivery.verify_candidate_delta(root, source, delta, candidate)
    assert result["ok"], result
    assert (root / ".git/index").read_bytes() == before


@pytest.mark.asyncio
async def test_git_executable_metadata_is_distinct_from_unexecutable_physical_files(repository, tmp_path):
    root = repository
    git(root, "config", "core.filemode", "false")
    for name in ("run.sh", "unchanged.sh"):
        (root / name).chmod(0o644)
    (root / "run.sh").write_bytes(b"#!/bin/sh\necho working\n")
    before = (root / ".git/index").read_bytes()
    candidate = tmp_path / "candidate"
    git(root, "worktree", "add", "--detach", str(candidate), "HEAD")
    source = await evidence.source_snapshot(root)
    for name in ("run.sh", "unchanged.sh"):
        assert source["files"][name]["mode"] == "100644"
        assert source["git_files"][name]["mode"] == "100755"
    await evidence.apply_source_snapshot(candidate, source)
    assert physical(candidate) == physical(root)
    assert (await evidence.verify_patch_delivery(root, source["base_head"], source["patch"], candidate))["ok"]
    assert await delivery.export_candidate_delta(candidate, source) == ""
    assert (root / ".git/index").read_bytes() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("attribute", ["filter=forbidden", "ident", "working-tree-encoding=UTF-16"])
async def test_unsupported_transformations_fail_before_export(repository, attribute):
    root = repository
    (root / ".gitattributes").write_bytes(f"*.txt {attribute}\n".encode())
    git(root, "config", "filter.forbidden.clean", "this-command-must-never-run")
    before = (root / ".git/index").read_bytes()
    with pytest.raises(evidence.EvidenceError, match="filters|transformation"):
        await evidence.source_snapshot(root)
    assert (root / ".git/index").read_bytes() == before


@pytest.mark.asyncio
async def test_overlay_replaces_tracked_directory_with_file(repository, tmp_path):
    root = repository
    target = root / "delete.txt"
    target.unlink()
    target.mkdir()
    (target / "child.txt").write_bytes(b"tracked child\n")
    git(root, "add", "--all")
    git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "directory fixture")
    candidate = tmp_path / "candidate"
    git(root, "worktree", "add", "--detach", str(candidate), "HEAD")
    (target / "child.txt").unlink()
    target.rmdir()
    target.write_bytes(b"physical replacement\n")
    source = await evidence.source_snapshot(root)
    await evidence.apply_source_snapshot(candidate, source)
    assert physical(candidate) == physical(root)


@pytest.mark.asyncio
async def test_sensitive_edits_hidden_by_index_flags_fail_with_text_normalization(repository):
    root = repository
    (root / ".gitattributes").write_bytes(b".env.local text eol=crlf\n")
    git(root, "add", ".gitattributes")
    git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "attributes")
    git(root, "update-index", "--assume-unchanged", ".env.local")
    (root / ".env.local").write_bytes(b"changed private fixture\r\n")
    before = (root / ".git/index").read_bytes()
    with pytest.raises(evidence.EvidenceError, match="sensitive tracked"):
        await evidence.source_snapshot(root)
    assert (root / ".git/index").read_bytes() == before


def test_saved_patch_and_text_keep_lf_and_existing_crlf(tmp_path):
    patch = "diff --git a/page.txt b/page.txt\n--- a/page.txt\n+++ b/page.txt\n@@ -1 +1 @@\n-old\r\n+new\r\n"
    path = tmp_path / "winner.patch"
    assert mcp_code_server._write_patch(path, patch) == patch
    assert path.read_bytes() == patch.encode("utf-8")
    assert not path.with_name(path.name + ".new").exists()


def test_saved_patch_readback_refuses_changed_bytes(tmp_path, monkeypatch):
    path = tmp_path / "winner.patch"
    monkeypatch.setattr(mcp_code_server, "_write_text", lambda target, text: target.write_bytes(text.replace("\n", "\r\n").encode("utf-8")))
    with pytest.raises(RuntimeError, match="Saved patch bytes differ"):
        mcp_code_server._write_patch(path, "expected\n")


@pytest.mark.asyncio
async def test_binary_git_replay_cancellation_drains_paused_output(repository, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from frontend_design_loop_core import utils

    entered = asyncio.Event()
    processes = []
    real_communicate = []

    async def launch(*args, **kwargs):
        process = await utils.launch_process_argv(
            [sys.executable, "-c", "import sys,time;sys.stdout.buffer.write(b'x'*1000000);sys.stdout.buffer.flush();time.sleep(60)"],
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        processes.append(process)
        if os.name != "nt":
            # Exercise Windows' immediate host-kill strategy with real local
            # pipes; POSIX's signal grace can hide this paused-reader failure.
            monkeypatch.setattr(utils, "os", SimpleNamespace(name="nt"))
        original = process.communicate
        real_communicate.append(original)
        calls = 0

        async def communicate(input=None):
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                await asyncio.Event().wait()
            return await original(input)

        process.communicate = communicate
        return process

    monkeypatch.setattr(evidence, "launch_process_argv", launch)
    tree = tmp_path / "replay"
    tree.mkdir()
    task = asyncio.create_task(evidence._materialize_index(repository, tree, evidence._git_env()))
    try:
        await asyncio.wait_for(entered.wait(), 10)
        process = processes[0]

        async def paused():
            while not process.stdout._paused:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(paused(), 10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 4)
        assert process.returncode is not None
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        for process, communicate in zip(processes, real_communicate):
            process.communicate = communicate
            await utils.terminate_process_tree(process, drain_output=True)
