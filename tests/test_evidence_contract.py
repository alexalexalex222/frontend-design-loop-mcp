"""Evidence contracts exercised against real temporary repositories and working trees."""

import asyncio
import copy
import os
import stat
import subprocess
import time
from pathlib import Path

import pytest

from frontend_design_loop_core import evidence


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True).stdout.decode()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "source with spaces & 'quotes'"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "core.autocrlf", "false")
    (root / "page.txt").write_bytes(b"original\n")
    (root / "deleted.txt").write_bytes(b"delete me\n")
    (root / "binary.dat").write_bytes(b"old\x00data")
    (root / ".gitignore").write_text("node_modules/\n.env.local\nignored-source/\n*.log\n")
    git(root, "add", ".")
    git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")
    return root


@pytest.fixture
def candidate(repo: Path, tmp_path: Path) -> Path:
    dest = tmp_path / "candidate & with spaces"
    git(repo, "worktree", "add", "--detach", str(dest), "HEAD")
    yield dest
    git(repo, "worktree", "remove", "--force", str(dest))


def legacy(**kwargs) -> dict:
    result = {"broken": {"broken": False, "confidence": 1.0, "reasons": []}, "score": {"score": 9.0, "pass": True}}
    result.update(kwargs)
    return result


def strict(**kwargs) -> dict:
    result = {
        "schema_version": 1, "status": "assessed", "broken": False, "score": 9.0,
        "pass": True, "blockers": [], "uncertainty": [], "limits": [],
        "evidence": {"kind": "ui", "sufficient": True, "observations": [{"image": "desktop.png", "finding": "Readable headings"}]},
    }
    result.update(kwargs)
    return result


def test_legacy_and_canonical_reports_are_strict_and_idempotent():
    report = legacy()
    report["score"]["strengths"] = ["Readable headings"]
    original = copy.deepcopy(report)
    canonical = evidence.validate_visual_report(report)
    assert report == original
    assert canonical["score"] == 9.0
    assert canonical["broken"] is False
    assert canonical["strengths"] == ["Readable headings"]
    assert canonical["limits"] == ["Legacy report does not identify its visual evidence"]
    assert evidence.validate_visual_report(canonical) == canonical
    assert evidence.visual_verdict(report, 8.4) == (True, 9.0)
    assert evidence.visual_verdict(strict(), 9.0) == (True, 9.0)


@pytest.mark.parametrize("score", ["9", True, float("nan"), float("inf"), -float("inf"), -0.1, 10.1, 999, 10**1000, {}, []])
def test_invalid_scores_never_pass(score):
    report = legacy()
    report["score"]["score"] = score
    with pytest.raises(evidence.VisualReportError):
        evidence.validate_visual_report(report)
    assert evidence.visual_verdict(report, 8) == (False, None)


@pytest.mark.parametrize("broken", ["false", "true", 0, 1, {}, []])
def test_broken_assessment_is_not_truthiness(broken):
    report = legacy()
    report["broken"]["broken"] = broken
    with pytest.raises(evidence.VisualReportError):
        evidence.validate_visual_report(report)
    assert evidence.visual_verdict(report, 8) == (False, None)


@pytest.mark.parametrize("report", [
    {}, {"score": {"score": 9}}, {"broken": {"broken": False}},
    {"broken": {}, "score": {"score": 9}}, {"broken": {"broken": False}, "score": {}},
    {"broken": None, "score": {"score": 9}},
    legacy(score={"score": 9, "pass": "false"}),
    legacy(broken={"broken": False, "confidence": float("inf")}),
    legacy(broken={"broken": False, "reasons": None}),
    strict(evidence=None), strict(evidence={"kind": "ui", "sufficient": "true", "observations": []}),
    strict(schema_version=True), strict(schema_version=2), strict(status="assessed", score=None),
    strict(status="error", score=None, broken=None, **{"pass": True}),
    strict(status="uncertain", score=None, broken=None, **{"pass": None}),
])
def test_malformed_assessments_are_evaluator_errors(report):
    with pytest.raises(evidence.VisualReportError):
        evidence.validate_visual_report(report)
    assert evidence.visual_verdict(report, 8) == (False, None)


@pytest.mark.parametrize("report", [
    strict(**{"pass": False}), strict(broken=True), strict(blockers=["Missing mobile navigation"]),
    strict(evidence={"kind": "proxy", "sufficient": True, "observations": ["Diff image"]}),
    strict(evidence={"kind": "insufficient", "sufficient": False, "observations": []}),
    strict(evidence={"kind": "ui", "sufficient": False, "observations": []}),
    legacy(broken={"broken": False, "confidence": 1, "reasons": ["diff_mode"]}),
    legacy(kind="diff"), legacy(evidence_kind="proxy"),
])
def test_blockers_false_pass_or_proxy_are_not_visual_passes(report):
    assert evidence.visual_verdict(report, 8.4) == (False, 9.0)


def test_uncertainty_and_error_remain_separate_from_design_failure():
    uncertain = strict(status="uncertain", score=None, broken=None, uncertainty=["Images unavailable"], **{"pass": None})
    failed = strict(score=3, broken=True, **{"pass": False})
    error = strict(status="error", score=None, broken=None, error="Judge timed out", **{"pass": None})
    assert evidence.validate_visual_report(uncertain)["status"] == "uncertain"
    assert evidence.validate_visual_report(error)["status"] == "error"
    assert evidence.validate_visual_report(failed)["status"] == "assessed"
    assert evidence.visual_verdict(uncertain, 8) == (False, None)
    assert evidence.visual_verdict(error, 8) == (False, None)
    assert evidence.visual_verdict(failed, 8) == (False, 3.0)


@pytest.mark.parametrize("threshold", ["8", True, -1, 11, float("nan"), float("inf")])
def test_invalid_threshold_is_a_configuration_error(threshold):
    with pytest.raises(evidence.VisualReportError):
        evidence.visual_verdict(strict(), threshold)


@pytest.mark.asyncio
async def test_real_export_replays_new_binary_deleted_and_mode_files_without_index_mutation(repo, candidate):
    head = git(repo, "rev-parse", "HEAD").strip()
    index_before = (repo / ".git" / "index").read_bytes()
    refs_before = git(repo, "show-ref")
    (repo / "page.txt").write_bytes(b"staged revision\n")
    git(repo, "add", "page.txt")
    staged_index = (repo / ".git" / "index").read_bytes()
    (repo / "page.txt").write_bytes(b"working revision\n")
    (repo / "new style.css").write_bytes(b"body { color: blue; }\n")
    (repo / "binary.dat").write_bytes(bytes(range(256)) + b"\x00new")
    (repo / "added-binary.dat").write_bytes(b"\x00brand new\xff")
    (repo / "deleted.txt").unlink()
    (repo / "script.sh").write_bytes(b"#!/bin/sh\necho yes\n")
    if os.name != "nt":
        (repo / "script.sh").chmod(0o755)
        (repo / "page.txt").chmod(0o755)
    patch = await evidence.export_patch(repo)
    assert "new style.css" in patch
    assert "GIT binary patch" in patch
    assert "deleted file mode" in patch
    assert (repo / ".git" / "index").read_bytes() == staged_index != index_before
    assert git(repo, "show-ref") == refs_before
    assert git(repo, "rev-parse", "HEAD").strip() == head
    snapshot = await evidence.source_snapshot(repo)
    assert snapshot["patch"] == patch
    assert snapshot["source_status"]["dirty"] is True
    await evidence.apply_source_snapshot(candidate, snapshot)
    assert (candidate / "page.txt").read_bytes() == b"working revision\n"
    assert (candidate / "new style.css").read_bytes() == (repo / "new style.css").read_bytes()
    assert (candidate / "binary.dat").read_bytes() == (repo / "binary.dat").read_bytes()
    assert (candidate / "added-binary.dat").read_bytes() == (repo / "added-binary.dat").read_bytes()
    assert not (candidate / "deleted.txt").exists()
    if os.name != "nt":
        assert (candidate / "script.sh").stat().st_mode & stat.S_IXUSR
        assert (candidate / "page.txt").stat().st_mode & stat.S_IXUSR
    verification = await evidence.verify_patch_delivery(repo, head, patch, candidate)
    assert verification["ok"], verification
    assert verification["replay_fingerprint"] == snapshot["fingerprint"]
    assert (repo / ".git" / "index").read_bytes() == staged_index
    assert git(repo, "show-ref") == refs_before


@pytest.mark.asyncio
async def test_dirty_source_snapshot_preserves_staged_addition_working_deletion_and_symlink(repo, candidate):
    (repo / "staged.css").write_text("staged\n")
    git(repo, "add", "staged.css")
    (repo / "staged.css").write_text("working contents instead\n")
    git(repo, "rm", "deleted.txt")
    (repo / "untracked.txt").write_text("keep untracked\n")
    if os.name != "nt":
        (repo / "page-link").symlink_to("page.txt")
    snapshot = await evidence.source_snapshot(repo)
    await evidence.apply_source_snapshot(candidate, snapshot)
    assert (candidate / "staged.css").read_text() == "working contents instead\n"
    assert (candidate / "untracked.txt").read_text() == "keep untracked\n"
    assert not (candidate / "deleted.txt").exists()
    if os.name != "nt":
        assert (candidate / "page-link").is_symlink()
        assert os.readlink(candidate / "page-link") == "page.txt"
    assert await evidence.export_patch(candidate) == snapshot["patch"]


@pytest.mark.asyncio
async def test_known_generated_ignored_paths_are_explicitly_excluded(repo):
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "dependency.js").write_text("generated\n")
    snapshot = await evidence.source_snapshot(repo)
    assert snapshot["patch"] == ""
    assert snapshot["source_status"]["excluded_ignored"] == ["node_modules/"]
    assert "node_modules/dependency.js" not in snapshot["files"]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [".env.local", "credentials.json", "private.key", "ignored-source/app.css"])
async def test_sensitive_and_unknown_ignored_content_is_excluded(repo, path):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("private value must not reach error output")
    snapshot = await evidence.source_snapshot(repo)
    assert path not in snapshot["files"]
    assert snapshot["patch"] == ""
    assert "private value" not in str(snapshot)
    assert snapshot["source_policy"]["exclusions"]
    assert snapshot["source_status"]["dirty"] is False


@pytest.mark.asyncio
async def test_tracked_sensitive_change_is_not_exported(repo):
    (repo / "credentials.json").write_text("original private value")
    git(repo, "add", "credentials.json")
    with pytest.raises(evidence.EvidenceError):
        await evidence.export_patch(repo)


@pytest.mark.asyncio
async def test_line_endings_are_preserved_and_filters_fail_explicitly(repo):
    (repo / ".gitattributes").write_text("*.txt text eol=lf\n")
    (repo / "page.txt").write_bytes(b"working\r\n")
    snapshot = await evidence.source_snapshot(repo)
    assert snapshot["files"]["page.txt"]["git_blob"] != snapshot["git_files"]["page.txt"]["git_blob"]
    assert "working\r\n" in snapshot["patch"]
    (repo / ".gitattributes").write_text("*.txt filter=dangerous\n")
    git(repo, "config", "filter.dangerous.clean", "this-program-must-not-be-called")
    with pytest.raises(evidence.EvidenceError, match="filters"):
        await evidence.export_patch(repo)


@pytest.mark.asyncio
async def test_git_redirect_environment_does_not_change_repository_selection(repo, monkeypatch, tmp_path):
    monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "wrong-index"))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path))
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "no-git"))
    assert (await evidence.source_snapshot(repo))["base_head"]
    assert not (tmp_path / "wrong-index").exists()


@pytest.mark.asyncio
async def test_private_index_keeps_racy_working_changes_visible(repo):
    git(repo, "config", "core.trustctime", "false")
    git(repo, "config", "core.checkStat", "minimal")
    page = repo / "page.txt"
    timestamp = int(time.time()) - 60
    os.utime(page, (timestamp, timestamp))
    git(repo, "add", "page.txt")
    index = repo / ".git" / "index"
    os.utime(index, (timestamp, timestamp))
    index_bytes, index_timestamp = index.read_bytes(), index.stat().st_mtime_ns
    page.write_bytes(b"modified\n")  # Same size and cached mtime as the original.
    os.utime(page, (timestamp, timestamp))

    snapshot = await evidence.source_snapshot(repo)
    assert " M page.txt\x00" in snapshot["source_status"]["porcelain"]
    assert "modified\n" in snapshot["patch"]
    assert index.read_bytes() == index_bytes
    assert index.stat().st_mtime_ns == index_timestamp


@pytest.mark.asyncio
async def test_snapshot_overlay_rejects_dirty_destination_and_corruption(repo, candidate):
    (repo / "page.txt").write_text("source changes\n")
    snapshot = await evidence.source_snapshot(repo)
    (candidate / "page.txt").write_text("candidate edits\n")
    with pytest.raises(evidence.EvidenceError, match="pristine"):
        await evidence.apply_source_snapshot(candidate, snapshot)
    assert (candidate / "page.txt").read_text() == "candidate edits\n"
    (candidate / "page.txt").write_bytes(b"original\n")
    corrupt = copy.deepcopy(snapshot)
    corrupt["patch"] = ""
    with pytest.raises(evidence.EvidenceError, match="reproduce"):
        await evidence.apply_source_snapshot(candidate, corrupt)
    assert (candidate / "page.txt").read_text() == "original\n"
    corrupt["fingerprint"] = "wrong"
    with pytest.raises(evidence.EvidenceError, match="fingerprint"):
        await evidence.apply_source_snapshot(candidate, corrupt)


@pytest.mark.asyncio
async def test_replay_detects_delivery_that_omits_new_file(repo, candidate):
    (candidate / "page.txt").write_text("changed\n")
    (candidate / "new.css").write_text("body { color: red; }\n")
    incomplete = git(candidate, "diff", "--binary", "HEAD")
    verification = await evidence.verify_patch_delivery(repo, git(repo, "rev-parse", "HEAD").strip(), incomplete, candidate)
    assert verification["ok"] is False
    assert verification["mismatches"] == ["new.css"]
    assert "error" not in verification


@pytest.mark.asyncio
async def test_failed_replay_is_nonmutating(repo, candidate):
    original_index = (repo / ".git" / "index").read_bytes()
    original = (candidate / "page.txt").read_bytes()
    result = await evidence.verify_patch_delivery(repo, git(repo, "rev-parse", "HEAD").strip(), "invalid patch", candidate)
    assert result["ok"] is False
    assert result["error"]
    assert (repo / ".git" / "index").read_bytes() == original_index
    assert (candidate / "page.txt").read_bytes() == original


@pytest.mark.asyncio
async def test_checkpoint_restores_versions_untracked_deleted_ignored_and_index(candidate):
    (candidate / "deleted.txt").unlink()
    (candidate / "untracked.txt").write_bytes(b"keep\x00original")
    (candidate / "node_modules").mkdir()
    (candidate / "node_modules" / "generated.js").write_text("original cache\n")
    if os.name != "nt":
        (candidate / "original-link").symlink_to("untracked.txt")
    index_path = Path(git(candidate, "rev-parse", "--git-path", "index").strip())
    if not index_path.is_absolute():
        index_path = candidate / index_path
    index_before = index_path.read_bytes()
    checkpoint = evidence.CandidateCheckpoint(candidate)
    await checkpoint.capture()
    try:
        (candidate / "page.txt").unlink()
        (candidate / "deleted.txt").write_text("resurrected\n")
        (candidate / "untracked.txt").write_text("wrong\n")
        (candidate / "new-dir").mkdir()
        (candidate / "new-dir" / "new.txt").write_text("introduced\n")
        (candidate / "node_modules" / "generated.js").write_text("changed cache\n")
        if os.name != "nt":
            (candidate / "original-link").unlink()
        git(candidate, "add", "--all")
        await checkpoint.restore()
        assert (candidate / "page.txt").read_bytes() == b"original\n"
        assert not (candidate / "deleted.txt").exists()
        assert (candidate / "untracked.txt").read_bytes() == b"keep\x00original"
        assert (candidate / "node_modules" / "generated.js").read_text() == "original cache\n"
        assert not (candidate / "new-dir").exists()
        assert index_path.read_bytes() == index_before
        if os.name != "nt":
            assert os.readlink(candidate / "original-link") == "untracked.txt"
        # A new capture establishes a later recoverable candidate version.
        (candidate / "page.txt").write_text("approved version two\n")
        await checkpoint.capture()
        (candidate / "page.txt").write_text("worse version three\n")
        await checkpoint.restore()
        assert (candidate / "page.txt").read_text() == "approved version two\n"
    finally:
        checkpoint.close()


@pytest.mark.asyncio
async def test_live_repository_cannot_be_checkpointed(repo):
    with pytest.raises(evidence.EvidenceError, match="live repository"):
        await evidence.CandidateCheckpoint(repo).capture()
    assert (repo / "page.txt").read_text() == "original\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["false", "exception", "cancel", "malformed"])
async def test_partial_bundle_failure_restores_complete_candidate(candidate, failure):
    (candidate / "deleted.txt").unlink()
    (candidate / "untracked.txt").write_text("preserved\n")
    before = await evidence.source_snapshot(candidate)

    async def application(*, repo_root, patches):
        assert repo_root == candidate and patches == [{"path": "page.txt", "patch": "bundle"}]
        (repo_root / "page.txt").write_text("partial changes\n")
        (repo_root / "untracked.txt").unlink()
        (repo_root / "deleted.txt").write_text("accidental resurrection\n")
        (repo_root / "new.txt").write_text("partial new file\n")
        if failure == "exception":
            raise RuntimeError("second patch failed")
        if failure == "cancel":
            raise asyncio.CancelledError()
        if failure == "malformed":
            return "false", ["page.txt"]
        return False, ["page.txt"]

    if failure == "false":
        assert await evidence.apply_patch_transaction(candidate, [{"path": "page.txt", "patch": "bundle"}], application) == (False, [])
    else:
        expected = {"exception": RuntimeError, "cancel": asyncio.CancelledError, "malformed": evidence.EvidenceError}[failure]
        with pytest.raises(expected):
            await evidence.apply_patch_transaction(candidate, [{"path": "page.txt", "patch": "bundle"}], application)
    after = await evidence.source_snapshot(candidate)
    assert after == before


@pytest.mark.asyncio
async def test_actual_task_cancellation_restores_candidate(candidate):
    entered = asyncio.Event()

    async def application(*, repo_root, patches):
        (repo_root / "page.txt").write_text("partial\n")
        entered.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(evidence.apply_patch_transaction(candidate, [], application))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (candidate / "page.txt").read_text() == "original\n"


@pytest.mark.asyncio
async def test_successful_transaction_keeps_changes_and_supports_plain_injected_candidate(tmp_path):
    (tmp_path / "page.txt").write_text("original\n")

    def application(*, repo_root, patches):
        (repo_root / "page.txt").write_text("successful\n")
        return True, ["page.txt"]

    assert await evidence.apply_patch_transaction(tmp_path, [], application) == (True, ["page.txt"])
    assert (tmp_path / "page.txt").read_text() == "successful\n"


def test_nested_evidence_contract_matches_controller_judge_and_preserves_uncertainty():
    report = legacy(score={
        "assessment": "excellent", "score": 9, "issues": [], "highlights": ["Clear hierarchy"],
        "fix_suggestions": [], "blockers": [], "evidence": ["desktop.png: Clear headings"],
        "limitations": ["Keyboard behavior unverified"], "baseline_comparison": "no_baseline",
    })
    canonical = evidence.validate_visual_report(report)
    assert canonical["strengths"] == ["Clear hierarchy"]
    assert canonical["limits"] == ["Keyboard behavior unverified"]
    assert evidence.visual_verdict(canonical, 8.4) == (True, 9.0)
    report["score"]["assessment"] = "uncertain"
    report["score"]["score"] = None
    report["score"]["evidence"] = []
    canonical = evidence.validate_visual_report(report)
    assert canonical["status"] == "uncertain"
    assert canonical["uncertainty"]
    assert evidence.visual_verdict(canonical, 8.4) == (False, None)


def test_empty_observations_and_nested_blockers_cannot_be_hidden_by_top_level():
    report = legacy(blockers=[])
    report["score"]["blockers"] = ["Observed blocker"]
    assert evidence.visual_verdict(report, 8) == (False, 9.0)
    report["score"]["blockers"] = []
    report["score"]["evidence"] = []
    assert evidence.visual_verdict(report, 8) == (False, 9.0)


@pytest.mark.parametrize("report", [
    legacy(status="assessed", uncertain=True),
    legacy(status="assessed", score={"score": 9, "status": "uncertain"}),
    legacy(confidence=1, broken={"broken": False, "confidence": "1"}),
    legacy(score={"score": 9, "pass": True, "uncertain": True}),
])
def test_contradictory_or_string_assessments_fail_closed(report):
    assert evidence.visual_verdict(report, 8) == (False, None)


@pytest.mark.parametrize("report", [
    strict(assessment="uncertain", score=8.5),
    legacy(assessment="uncertain", status="assessed", score={"score": 8.5, "pass": True}),
    legacy(assessment="good", score={"score": 8.5, "assessment": "uncertain"}),
    legacy(assessment="uncertain", score={"score": 8.5, "assessment": "good"}),
    strict(assessment="unsupported"),
])
def test_top_level_assessment_cannot_contradict_a_visual_pass(report):
    with pytest.raises(evidence.VisualReportError):
        evidence.validate_visual_report(report)
    assert evidence.visual_verdict(report, 8) == (False, None)


@pytest.mark.parametrize("report", [
    strict(assessment="uncertain", status="uncertain", score=8.5,
           uncertainty=["Mobile image missing"], **{"pass": False}),
    legacy(assessment="uncertain", score={"score": 8.5, "pass": False}),
    legacy(score={"score": 8.5, "pass": False, "assessment": "uncertain"}),
])
def test_consistent_uncertain_assessment_stays_uncertain_after_normalization(report):
    canonical = evidence.validate_visual_report(report)
    assert canonical["status"] == "uncertain"
    assert evidence.validate_visual_report(canonical) == canonical
    assert evidence.visual_verdict(report, 8) == (False, 8.5)


def test_circular_report_fails_closed():
    report = strict()
    report["additional_evidence"] = report
    assert evidence.visual_verdict(report, 8) == (False, None)


@pytest.mark.asyncio
async def test_real_export_and_replay_supports_file_directory_replacement(repo, candidate):
    (repo / "deleted.txt").unlink()
    (repo / "deleted.txt").mkdir()
    (repo / "deleted.txt" / "inside.css").write_text("new child\n")
    snapshot = await evidence.source_snapshot(repo)
    await evidence.apply_source_snapshot(candidate, snapshot)
    assert (candidate / "deleted.txt" / "inside.css").read_text() == "new child\n"
    first = await evidence.verify_patch_delivery(repo, snapshot["base_head"], snapshot["patch"], candidate)
    assert first["ok"], first
    # Replay the inverse transition from a real committed directory fixture.
    git(repo, "add", "--all")
    git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "directory fixture")
    (repo / "deleted.txt" / "inside.css").unlink()
    (repo / "deleted.txt").rmdir()
    (repo / "deleted.txt").write_text("file replaces directory\n")
    snapshot = await evidence.source_snapshot(repo)
    # Delivery verification accepts an explicitly isolated standalone fixture too.
    result = await evidence.verify_patch_delivery(repo, snapshot["base_head"], snapshot["patch"], repo)
    assert result["ok"], result


@pytest.mark.asyncio
@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink and executable fixture")
async def test_mode_only_delta_and_internal_symlink_replay(repo, candidate):
    (repo / "page.txt").chmod(0o755)
    (repo / "linked-file").symlink_to("page.txt")
    snapshot = await evidence.source_snapshot(repo)
    assert "old mode 100644" in snapshot["patch"]
    assert "new mode 100755" in snapshot["patch"]
    await evidence.apply_source_snapshot(candidate, snapshot)
    assert (candidate / "page.txt").read_text() == "original\n"
    assert (candidate / "page.txt").stat().st_mode & stat.S_IXUSR
    result = await evidence.verify_patch_delivery(repo, snapshot["base_head"], snapshot["patch"], candidate)
    assert result["ok"], result


@pytest.mark.asyncio
@pytest.mark.skipif(os.name == "nt", reason="POSIX escaping symlink fixture")
async def test_untracked_symlink_cannot_export_external_contents(repo, tmp_path):
    external = tmp_path / "private-file"
    external.write_text("do not export")
    (repo / "outside-link").symlink_to(external)
    with pytest.raises(evidence.EvidenceError, match="escapes"):
        await evidence.source_snapshot(repo)


@pytest.mark.asyncio
async def test_source_mutation_during_export_is_detected(repo, monkeypatch):
    (repo / "page.txt").write_text("initial dirty content\n")
    index = (repo / ".git" / "index").read_bytes()
    original_git = evidence._git

    async def racing_git(repo, args, **kwargs):
        output = await original_git(repo, args, **kwargs)
        if args[0] == "diff" and "--cached" in args:
            (repo / "page.txt").write_text("concurrent source mutation\n")
        return output

    monkeypatch.setattr(evidence, "_git", racing_git)
    with pytest.raises(evidence.EvidenceError, match="changed while"):
        await evidence.source_snapshot(repo)
    assert (repo / ".git" / "index").read_bytes() == index


@pytest.mark.asyncio
async def test_checkpoint_restores_readonly_files_and_permissions(candidate):
    (candidate / "readonly.txt").write_text("readonly original\n")
    (candidate / "readonly.txt").chmod(0o444)
    original_mode = stat.S_IMODE((candidate / "readonly.txt").stat().st_mode)
    checkpoint = evidence.CandidateCheckpoint(candidate)
    await checkpoint.capture()
    try:
        (candidate / "readonly.txt").chmod(0o644)
        (candidate / "readonly.txt").write_text("changed\n")
        (candidate / "readonly.txt").chmod(0o444)
        await checkpoint.restore()
        assert (candidate / "readonly.txt").read_text() == "readonly original\n"
        assert stat.S_IMODE((candidate / "readonly.txt").stat().st_mode) == original_mode
    finally:
        checkpoint.close()
        (candidate / "readonly.txt").chmod(0o644)


@pytest.mark.asyncio
async def test_run_argv_is_injectable_and_private_git_errors_are_not_forwarded(tmp_path, monkeypatch):
    calls = []

    async def fake_run_argv(args, **kwargs):
        calls.append((args, kwargs))
        return 31, "", "a private value from a configured process"

    monkeypatch.setattr(evidence, "run_argv", fake_run_argv)
    with pytest.raises(evidence.EvidenceError) as error:
        await evidence.export_patch(tmp_path)
    assert "private value" not in str(error.value)
    assert calls[0][1]["cwd"] == tmp_path
    assert calls[0][0][0] == "git"


@pytest.mark.asyncio
async def test_temporary_storage_inside_source_or_candidate_cannot_capture_itself(repo, candidate, monkeypatch):
    import tempfile

    (repo / "page.txt").write_text("source changes\n")
    monkeypatch.setattr(tempfile, "tempdir", str(repo))
    snapshot = await evidence.source_snapshot(repo)
    assert all("frontend-design-loop-" not in path for path in snapshot["files"])
    await evidence.apply_source_snapshot(candidate, snapshot)
    result = await evidence.verify_patch_delivery(repo, snapshot["base_head"], snapshot["patch"], candidate)
    assert result["ok"], result
    monkeypatch.setattr(tempfile, "tempdir", str(candidate))
    checkpoint = evidence.CandidateCheckpoint(candidate)
    await checkpoint.capture()
    try:
        (candidate / "page.txt").write_text("temporary version\n")
        await checkpoint.restore()
        assert (candidate / "page.txt").read_text() == "source changes\n"
        assert not any(path.name.startswith("frontend-design-loop-") for path in candidate.iterdir())
    finally:
        checkpoint.close()


@pytest.mark.asyncio
async def test_transaction_does_not_allow_patches_to_git_metadata(candidate):
    marker = (candidate / ".git").read_bytes()

    async def application(**kwargs):
        pytest.fail("Git metadata patches must not reach the application callback")

    assert await evidence.apply_patch_transaction(candidate, [{"path": ".git", "patch": "bad"}], application) == (False, [])
    assert (candidate / ".git").read_bytes() == marker


@pytest.mark.asyncio
async def test_non_utf8_text_fails_instead_of_delivering_replacement_bytes(repo, candidate):
    (repo / "opaque.bin").write_bytes(b"\xff\xfeinvalid text without nul")
    with pytest.raises(evidence.EvidenceError, match="undecodable|replacement"):
        await evidence.export_patch(repo)
    # Explicit Git binary attributes give this same file a lossless supported delta.
    (repo / ".gitattributes").write_text("*.bin binary\n")
    snapshot = await evidence.source_snapshot(repo)
    assert "GIT binary patch" in snapshot["patch"]
    await evidence.apply_source_snapshot(candidate, snapshot)
    assert (candidate / "opaque.bin").read_bytes() == (repo / "opaque.bin").read_bytes()
    result = await evidence.verify_patch_delivery(repo, snapshot["base_head"], snapshot["patch"], candidate)
    assert result["ok"], result


@pytest.mark.parametrize("marker", ["text", "image_proxy", "proxy_structural", "insufficient"])
def test_explicit_evidence_markers_cannot_be_overridden_by_ui_label(marker):
    report = strict(evidence_kind=marker)
    assert evidence.visual_verdict(report, 8) == (False, 9.0)
