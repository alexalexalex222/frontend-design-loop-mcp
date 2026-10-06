"""Offline delivery and lifecycle integration checks; no provider or model calls."""

import asyncio
import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path

import pytest

from frontend_design_loop_core import delivery, evidence
from frontend_design_loop_core import execution_context as context
from frontend_design_loop_core.jobs import JobRegistry


def git(root: Path, *args: str) -> bytes:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_OPTIONAL_LOCKS="0",
        GIT_TERMINAL_PROMPT="0",
    )
    return subprocess.run(
        ["git", "-c", "core.fsmonitor=false", *args],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
    ).stdout


def index_bytes(root: Path) -> bytes:
    path = Path(os.fsdecode(git(root, "rev-parse", "--git-path", "index")).strip())
    return (path if path.is_absolute() else root / path).read_bytes()


def git_identity(root: Path) -> tuple[bytes, ...]:
    """Objects may be written, but delivery must not create commits or change refs."""
    return (
        git(root, "rev-parse", "HEAD"),
        git(root, "show-ref"),
        git(root, "rev-list", "--all"),
        git(root, "worktree", "list", "--porcelain"),
        b"\n".join(
            sorted(
                line
                for line in git(
                    root, "cat-file", "--batch-all-objects", "--batch-check"
                ).splitlines()
                if b" commit " in line
            )
        ),
    )


def contents(root: Path) -> dict:
    """Compare actual payloads/modes independently of production fingerprints."""
    result = {}
    for directory, dirs, names in os.walk(root):
        dirs[:] = [name for name in dirs if name != ".git"]
        for name in names:
            path = Path(directory) / name
            if path.name == ".git":
                continue
            mode = path.lstat().st_mode
            result[path.relative_to(root).as_posix()] = (
                "link" if stat.S_ISLNK(mode) else "file",
                os.fsencode(os.readlink(path)) if stat.S_ISLNK(mode) else path.read_bytes(),
                bool(mode & 0o111) if stat.S_ISREG(mode) else False,
            )
    return result


@pytest.fixture
def repository(tmp_path, monkeypatch):
    for key in list(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_OPTIONAL_LOCKS", "0")
    root = tmp_path / "user repo with spaces & quotes'"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "core.filemode", "true")
    git(root, "config", "core.autocrlf", "false")
    for name, payload in {
        "page.txt": b"committed page\n",
        "delete.txt": b"delete in candidate\n",
        "baseline-delete.txt": b"delete in source\n",
        "binary.dat": b"committed\0\xff\x01",
        "run.sh": b"#!/bin/sh\necho fixture\n",
    }.items():
        (root / name).write_bytes(payload)
    git(root, "add", "--all")
    # Bootstrap the disposable fixture only; tested operations must add no commits.
    git(
        root,
        "-c",
        "user.name=Offline Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "fixture baseline",
    )
    return root


@pytest.fixture
def worktree(repository, tmp_path):
    candidate = tmp_path / "detached candidate"
    git(repository, "worktree", "add", "--detach", str(candidate), "HEAD")
    try:
        yield candidate
    finally:
        git(repository, "worktree", "remove", "--force", str(candidate))


def dirty_baseline(root: Path) -> None:
    (root / "page.txt").write_bytes(b"user staged page\n")
    (root / "user-added.txt").write_bytes(b"user staged addition\n")
    git(root, "add", "page.txt", "user-added.txt")
    (root / "page.txt").write_bytes(b"user working page\n")
    (root / "user-added.txt").write_bytes(b"user working addition\n")
    (root / "baseline-delete.txt").unlink()
    (root / "binary.dat").write_bytes(b"user binary\0\xfe\x02")
    (root / "user-untracked.txt").write_bytes(b"user untracked baseline\n")


@pytest.mark.asyncio
@pytest.mark.parametrize("dirty", [False, True], ids=["clean-source", "staged-and-dirty-source"])
async def test_delta_replay_exactly_matches_working_contents_and_preserves_user_index(
    repository, worktree, tmp_path, dirty
):
    if dirty:
        dirty_baseline(repository)
    original = contents(repository)
    user_index = index_bytes(repository)
    identity = git_identity(repository)
    staged = git(repository, "diff", "--cached", "--binary")
    source = await evidence.source_snapshot(repository)
    await evidence.apply_source_snapshot(worktree, source)
    assert contents(worktree) == original

    (worktree / "page.txt").write_bytes(b"delivered candidate page\n")
    (worktree / "delete.txt").unlink()
    (worktree / "binary.dat").write_bytes(b"candidate binary\0\xff\x03")
    (worktree / "new binary.dat").write_bytes(bytes(range(256)))
    (worktree / "new page.txt").write_bytes(b"new UTF-8 page \xe2\x9c\x93\n")
    if dirty:
        (worktree / "user-added.txt").write_bytes(b"candidate replaces user addition\n")
        (worktree / "user-untracked.txt").unlink()
    if os.name != "nt":
        (worktree / "run.sh").chmod(0o755)
    # Candidate staged intent differs from the working content, too.
    git(worktree, "add", "page.txt", "new page.txt")
    (worktree / "new page.txt").write_bytes(b"final unstaged UTF-8 page \xe2\x9c\x93\n")
    candidate_index = index_bytes(worktree)
    expected = contents(worktree)

    delta = await delivery.export_candidate_delta(worktree, source)
    assert "GIT binary patch" in delta
    assert "delete.txt" in delta
    if os.name != "nt":
        assert "new mode 100755" in delta
    verification = await delivery.verify_candidate_delta(repository, source, delta, worktree)
    assert verification["ok"], verification
    assert verification["candidate_fingerprint"] == verification["replay_fingerprint"]

    # Independently apply the source-relative artifact rather than trusting ok alone.
    replay = tmp_path / "independent replay"
    git(repository, "worktree", "add", "--detach", str(replay), source["base_head"])
    try:
        await evidence.apply_source_snapshot(replay, source)
        patch = tmp_path / "delivery.patch"
        patch.write_bytes(delta.encode("utf-8"))
        git(replay, "apply", "--binary", str(patch))
        assert contents(replay) == expected
        assert git(replay, "diff", "--cached") == b""
    finally:
        git(repository, "worktree", "remove", "--force", str(replay))
    assert contents(repository) == original
    assert contents(worktree) == expected
    assert index_bytes(repository) == user_index
    assert index_bytes(worktree) == candidate_index
    assert git(repository, "diff", "--cached", "--binary") == staged
    assert git_identity(repository) == identity


@pytest.mark.asyncio
async def test_unchanged_dirty_candidate_delivers_empty_delta(repository, worktree):
    dirty_baseline(repository)
    source = await evidence.source_snapshot(repository)
    assert source["patch"]
    await evidence.apply_source_snapshot(worktree, source)
    identity, original_index = git_identity(repository), index_bytes(repository)
    delta = await delivery.export_candidate_delta(worktree, source)
    assert delta == ""
    result = await delivery.verify_candidate_delta(repository, source, delta, worktree)
    assert result["ok"], result
    assert contents(repository) == contents(worktree)
    assert index_bytes(repository) == original_index
    assert git_identity(repository) == identity


@pytest.mark.asyncio
@pytest.mark.parametrize("patch", ["", "invalid patch\n"], ids=["omitted-change", "malformed"])
async def test_replay_failure_removes_temporary_worktree_and_preserves_both_indexes(
    repository, worktree, patch
):
    dirty_baseline(repository)
    source = await evidence.source_snapshot(repository)
    await evidence.apply_source_snapshot(worktree, source)
    (worktree / "new.txt").write_bytes(b"must not be omitted\n")
    before = (
        git_identity(repository),
        index_bytes(repository),
        index_bytes(worktree),
        contents(repository),
        contents(worktree),
    )
    result = await delivery.verify_candidate_delta(repository, source, patch, worktree)
    after = (
        git_identity(repository),
        index_bytes(repository),
        index_bytes(worktree),
        contents(repository),
        contents(worktree),
    )
    assert after == before
    assert result["ok"] is False
    if patch:
        assert result["error"]
    else:
        assert result["candidate_fingerprint"] != result["replay_fingerprint"]


@pytest.mark.asyncio
async def test_delivery_ignores_inherited_git_repository_redirection(
    repository, worktree, monkeypatch, tmp_path
):
    source = await evidence.source_snapshot(repository)
    (worktree / "page.txt").write_bytes(b"candidate\n")
    patch = await delivery.export_candidate_delta(worktree, source)
    before = git_identity(repository), index_bytes(repository), index_bytes(worktree)
    wrong_index = tmp_path / "unrelated-index"
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "unrelated-git-dir"))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path))
    monkeypatch.setenv("GIT_INDEX_FILE", str(wrong_index))
    result = await delivery.verify_candidate_delta(repository, source, patch, worktree)
    assert (git_identity(repository), index_bytes(repository), index_bytes(worktree)) == before
    assert not wrong_index.exists()
    assert result["ok"], result


@pytest.mark.asyncio
async def test_delta_temporary_storage_inside_candidate_does_not_enter_delivery(
    repository, worktree, monkeypatch
):
    dirty_baseline(repository)
    source = await evidence.source_snapshot(repository)
    await evidence.apply_source_snapshot(worktree, source)
    (worktree / "page.txt").write_bytes(b"candidate\n")
    expected = contents(worktree)
    before = git_identity(repository), index_bytes(repository), index_bytes(worktree)
    # Verification itself uses temporary worktrees; keep that separate from this probe.
    with monkeypatch.context() as local_patch:
        local_patch.setattr(tempfile, "tempdir", str(worktree))
        patch = await delivery.export_candidate_delta(worktree, source)
    assert contents(worktree) == expected
    assert (git_identity(repository), index_bytes(repository), index_bytes(worktree)) == before
    result = await delivery.verify_candidate_delta(repository, source, patch, worktree)
    assert result["ok"], result


@pytest.mark.asyncio
@pytest.mark.parametrize("setting", ["diff.noprefix", "color.ui"])
async def test_delta_is_replayable_with_user_git_diff_configuration(repository, worktree, setting):
    dirty_baseline(repository)
    source = await evidence.source_snapshot(repository)
    await evidence.apply_source_snapshot(worktree, source)
    (worktree / "page.txt").write_bytes(b"candidate\n")
    git(repository, "config", setting, "always" if setting == "color.ui" else "true")
    before = git_identity(repository), index_bytes(repository), index_bytes(worktree)
    patch = await delivery.export_candidate_delta(worktree, source)
    result = await delivery.verify_candidate_delta(repository, source, patch, worktree)
    assert (git_identity(repository), index_bytes(repository), index_bytes(worktree)) == before
    assert result["ok"], result


CONTEXT_VARIABLES = (
    context.role_settings,
    context.execution_dir,
    context.current_images,
    context.baseline_images,
    context.cleanup_callbacks,
)


def context_values() -> tuple:
    return tuple(variable.get() for variable in CONTEXT_VARIABLES)


@pytest.fixture
def parent_context(tmp_path):
    values = (
        {"auth_mode": "subscription", "builder_effort": "high", "parent": True},
        tmp_path / "parent-receipts",
        [tmp_path / "parent-current.png"],
        [tmp_path / "parent-baseline.png"],
        [],
    )
    tokens = [variable.set(value) for variable, value in zip(CONTEXT_VARIABLES, values)]
    try:
        yield values
    finally:
        for variable, token in reversed(list(zip(CONTEXT_VARIABLES, tokens))):
            variable.reset(token)


@pytest.mark.asyncio
async def test_concurrent_role_contexts_and_receipts_are_isolated(parent_context, tmp_path):
    entered = [asyncio.Event(), asyncio.Event()]
    release = asyncio.Event()
    cleaned = []

    @context.with_execution_context
    async def request(
        index, *, auth_mode, planner_effort, builder_effort, refiner_effort, judge_effort
    ):
        assert context.current_images.get() == context.baseline_images.get() == []
        assert context.cleanup_callbacks.get() == []
        directory = tmp_path / f"request-{index}"
        context.execution_dir.set(directory)
        context.current_images.get().append(directory / "current.png")
        context.baseline_images.get().append(directory / "baseline.png")

        async def cleanup():
            cleaned.append((index, context.execution_options("judge")))

        context.cleanup_callbacks.get().append(cleanup)
        entered[index].set()
        await release.wait()
        expected = {
            "planner_bold": planner_effort,
            "builder": builder_effort,
            "refine_reasoner": refiner_effort,
            "vision_score": judge_effort,
        }
        for role, effort in expected.items():
            assert context.execution_options(role) == {
                "reasoning_profile": effort,
                "auth_mode": auth_mode,
            }
        assert context.current_images.get() == [directory / "current.png"]
        assert context.baseline_images.get() == [directory / "baseline.png"]
        response = type("OfflineResponse", (), {"content": f"result-{index}", "raw_response": {}})()
        context.record_execution("judge", "offline-fixture", "system", f"request-{index}", response)
        return directory

    tasks = [
        asyncio.create_task(
            request(
                0,
                auth_mode="subscription",
                planner_effort="high",
                builder_effort="xhigh",
                refiner_effort="high",
                judge_effort="xhigh",
            )
        ),
        asyncio.create_task(
            request(
                1,
                auth_mode="api_key",
                planner_effort="low",
                builder_effort="medium",
                refiner_effort="low",
                judge_effort="medium",
            )
        ),
    ]
    try:
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in entered)), 3)
        assert context_values() == parent_context
        release.set()
        directories = await asyncio.wait_for(asyncio.gather(*tasks), 3)
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    for index, directory in enumerate(directories):
        files = list(directory.glob("*.json"))
        assert len(files) == 1
        record = json.loads(files[0].read_text())
        assert record["user_prompt"] == f"request-{index}"
        assert record["response"] == f"result-{index}"
        assert record["options"] == {
            "reasoning_profile": "xhigh" if index == 0 else "medium",
            "auth_mode": "subscription" if index == 0 else "api_key",
        }
        assert not list(directory.glob("*.new"))
    assert sorted(index for index, _ in cleaned) == [0, 1]
    assert context_values() == parent_context


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, RuntimeError, asyncio.CancelledError])
async def test_context_resets_and_cleanup_runs_lifo_after_body_exit(parent_context, failure):
    called = []

    @context.with_execution_context
    async def request(builder_effort="xhigh"):
        context.execution_dir.set(Path("child"))
        context.current_images.get().append(Path("child.png"))
        for name in ("first", "second"):

            async def cleanup(label=name):
                called.append(label)

            context.cleanup_callbacks.get().append(cleanup)
        if failure is not None:
            raise failure("body fixture failure")
        return "done"

    if failure is None:
        assert await request() == "done"
    else:
        with pytest.raises(failure):
            await request()
    assert called == ["second", "first"]
    assert context_values() == parent_context


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_context_resets_even_when_cleanup_raises(parent_context, failure):
    @context.with_execution_context
    async def request(builder_effort="xhigh"):
        context.execution_dir.set(Path("child"))
        context.current_images.get().append(Path("child.png"))

        async def cleanup():
            raise failure("cleanup fixture failure")

        context.cleanup_callbacks.get().append(cleanup)

    with pytest.raises(failure):
        await request()
    assert context_values() == parent_context


@pytest.mark.asyncio
async def test_failing_cleanup_does_not_skip_remaining_resource_cleanup(parent_context):
    called = []

    @context.with_execution_context
    async def request():
        async def earlier():
            called.append("earlier")

        async def failing():
            called.append("failing")
            raise RuntimeError("cleanup fixture failure")

        context.cleanup_callbacks.get().extend([earlier, failing])

    with pytest.raises(RuntimeError, match="cleanup fixture failure"):
        await request()
    assert called == ["failing", "earlier"]


async def drain_jobs(registry: JobRegistry) -> None:
    for job in registry.jobs.values():
        if not job.task.done():
            job.task.cancel()
    await asyncio.gather(*(job.task for job in registry.jobs.values()), return_exceptions=True)


@pytest.mark.asyncio
async def test_job_limit_is_atomic_and_completed_jobs_release_capacity():
    registry = JobRegistry(limit=2, retained=4)
    release = asyncio.Event()
    entered = [asyncio.Event(), asyncio.Event()]

    async def operation(index):
        entered[index].set()
        await release.wait()
        return {"worker": index}

    first = registry.start(lambda: operation(0))
    second = registry.start(lambda: operation(1))
    try:
        assert first["persistence"] == "MCP server lifetime"
        assert first["job_id"] != second["job_id"]
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in entered)), 3)

        def must_not_start():
            pytest.fail("A rejected job must not create an operation coroutine")

        with pytest.raises(ValueError, match="At most 2"):
            registry.start(must_not_start)
        assert registry.status(first["job_id"])["status"] == "running"
        release.set()
        await asyncio.wait_for(asyncio.gather(*(job.task for job in registry.jobs.values())), 3)
        assert registry.status(first["job_id"])["result"] == {"worker": 0}
        assert registry.status(second["job_id"])["result"] == {"worker": 1}
        third = registry.start(lambda: operation(0))
        await registry.jobs[third["job_id"]].task
        assert registry.status(third["job_id"])["status"] == "complete"
    finally:
        release.set()
        await drain_jobs(registry)


@pytest.mark.asyncio
async def test_job_cancellation_waits_for_context_cleanup_before_releasing_capacity(parent_context):
    registry = JobRegistry(limit=1)
    entered, cleanup_entered, cleanup_release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    cleaned = []

    @context.with_execution_context
    async def operation(builder_effort="xhigh"):
        async def cleanup():
            cleanup_entered.set()
            await cleanup_release.wait()
            cleaned.append(context.execution_options("builder"))

        context.cleanup_callbacks.get().append(cleanup)
        entered.set()
        await asyncio.Event().wait()

    job = registry.start(operation)
    cancellation = None
    try:
        await asyncio.wait_for(entered.wait(), 3)
        cancellation = asyncio.create_task(registry.cancel(job["job_id"]))
        await asyncio.wait_for(cleanup_entered.wait(), 3)
        assert not cancellation.done()
        assert registry.status(job["job_id"])["status"] == "running"
        with pytest.raises(ValueError, match="At most 1"):
            registry.start(operation)
        cleanup_release.set()
        state = await asyncio.wait_for(cancellation, 3)
        assert state["status"] == "cancelled"
        assert state["elapsed_s"] >= 0
        assert cleaned == [{"reasoning_profile": "xhigh", "auth_mode": "subscription"}]
        assert (await registry.cancel(job["job_id"]))["status"] == "cancelled"
        assert registry.status(job["job_id"])["status"] == "cancelled"
        assert len(cleaned) == 1
        assert context_values() == parent_context
    finally:
        cleanup_release.set()
        if cancellation is not None:
            await asyncio.gather(cancellation, return_exceptions=True)
        await drain_jobs(registry)


@pytest.mark.asyncio
async def test_cancel_before_job_starts_never_enters_operation():
    registry = JobRegistry()
    entered = []

    async def operation():
        entered.append(True)

    job = registry.start(operation)
    try:
        state = await registry.cancel(job["job_id"])
        assert state["status"] == "cancelled"
        assert entered == []
        assert registry.status(job["job_id"])["status"] == "cancelled"
    finally:
        await drain_jobs(registry)


@pytest.mark.asyncio
async def test_cancelled_background_transaction_restores_git_candidate_before_cleanup(
    repository, worktree, parent_context
):
    dirty_baseline(repository)
    source = await evidence.source_snapshot(repository)
    await evidence.apply_source_snapshot(worktree, source)
    before = (
        contents(worktree),
        index_bytes(worktree),
        contents(repository),
        index_bytes(repository),
        git_identity(repository),
    )
    entered = asyncio.Event()
    cleanup_observations = []
    registry = JobRegistry(limit=1)

    @context.with_execution_context
    async def operation():
        async def cleanup():
            cleanup_observations.append((contents(worktree), index_bytes(worktree)))

        context.cleanup_callbacks.get().append(cleanup)

        async def application(*, repo_root, patches):
            (repo_root / "page.txt").write_bytes(b"partial candidate edit\n")
            (repo_root / "binary.dat").write_bytes(b"partial\0binary")
            (repo_root / "new.txt").write_bytes(b"partial addition\n")
            (repo_root / "delete.txt").unlink()
            git(repo_root, "add", "--all")
            entered.set()
            await asyncio.Event().wait()

        return await evidence.apply_patch_transaction(worktree, [], application)

    job = registry.start(operation)
    try:
        await asyncio.wait_for(entered.wait(), 3)
        assert contents(worktree) != before[0]
        state = await asyncio.wait_for(registry.cancel(job["job_id"]), 3)
        assert state["status"] == "cancelled"
        assert cleanup_observations == [(before[0], before[1])]
        assert (
            contents(worktree),
            index_bytes(worktree),
            contents(repository),
            index_bytes(repository),
            git_identity(repository),
        ) == before
        assert context_values() == parent_context
    finally:
        await drain_jobs(registry)


@pytest.mark.asyncio
async def test_slow_job_cleanup_returns_cancelling_then_finishes_without_second_cancellation():
    registry = JobRegistry(limit=1)
    entered, cleanup_entered, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    cleaned = []

    async def operation():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleanup_entered.set()
            await release.wait()
            cleaned.append(True)

    job = registry.start(operation)
    try:
        await asyncio.wait_for(entered.wait(), 3)
        # Exercise the real bounded cancel wait; no mocked task or clock.
        state = await asyncio.wait_for(registry.cancel(job["job_id"]), 12)
        assert cleanup_entered.is_set()
        assert state["status"] == "cancelling"
        assert not registry.jobs[job["job_id"]].task.done()
        with pytest.raises(ValueError, match="At most 1"):
            registry.start(operation)
        release.set()
        result = await asyncio.wait_for(
            asyncio.gather(registry.jobs[job["job_id"]].task, return_exceptions=True), 3
        )
        assert isinstance(result[0], asyncio.CancelledError)
        assert cleaned == [True]
        assert registry.status(job["job_id"])["status"] == "cancelled"
    finally:
        release.set()
        await drain_jobs(registry)


@pytest.mark.asyncio
async def test_failed_job_status_and_cancellation_are_stable():
    registry = JobRegistry()

    async def operation():
        raise RuntimeError("offline job fixture failure")

    job = registry.start(operation)
    try:
        await asyncio.gather(registry.jobs[job["job_id"]].task, return_exceptions=True)
        state = registry.status(job["job_id"])
        assert state["status"] == "failed"
        assert state["error"] == "offline job fixture failure"
        assert "result" not in state
        assert (await registry.cancel(job["job_id"]))["status"] == "failed"
    finally:
        await drain_jobs(registry)


@pytest.mark.asyncio
async def test_cancellation_cleanup_error_returns_failed_job_status():
    registry = JobRegistry()
    entered = asyncio.Event()

    async def operation():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            raise RuntimeError("offline cancellation cleanup failure")

    job = registry.start(operation)
    try:
        await asyncio.wait_for(entered.wait(), 3)
        state = await registry.cancel(job["job_id"])
        assert state["status"] == "failed"
        assert state["error"] == "offline cancellation cleanup failure"
    finally:
        await drain_jobs(registry)


@pytest.mark.asyncio
async def test_job_retention_prunes_completed_results_but_keeps_running_job():
    registry = JobRegistry(limit=2, retained=3)
    release = asyncio.Event()

    async def waiting():
        await release.wait()
        return "running job finished"

    async def completed(index):
        return index

    running = registry.start(waiting)["job_id"]
    finished = []
    try:
        for index in range(6):
            key = registry.start(lambda index=index: completed(index))["job_id"]
            finished.append(key)
            await registry.jobs[key].task
            assert len(registry.jobs) <= 3
            assert registry.status(running)["status"] == "running"
        assert set(registry.jobs) == {running, *finished[-2:]}
        with pytest.raises(ValueError, match="Unknown job_id"):
            registry.status(finished[0])
        release.set()
        await registry.jobs[running].task
        assert registry.status(running)["result"] == "running job finished"
    finally:
        release.set()
        await drain_jobs(registry)


@pytest.mark.asyncio
async def test_unknown_job_status_and_cancel_are_explicit():
    registry = JobRegistry()
    with pytest.raises(ValueError, match="Unknown job_id"):
        registry.status("unknown")
    with pytest.raises(ValueError, match="Unknown job_id"):
        await registry.cancel("unknown")
