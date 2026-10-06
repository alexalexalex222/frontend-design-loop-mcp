"""Explicit native review of verified, labeled screenshot manifests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from frontend_design_loop_core.config import load_config
from frontend_design_loop_core.evidence import validate_visual_report, visual_verdict
from frontend_design_loop_core.providers.base import Message, ProviderFactory
from frontend_design_loop_core.utils import extract_json_strict


def _load(path: Path, label: str, offset: int) -> tuple[list[bytes], dict]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or not manifest.get("screenshots"):
        raise ValueError("A capture_screenshots manifest with screenshots is required")
    images, shots = [], []
    for shot in manifest["screenshots"]:
        image_path = Path(shot["path"]).resolve()
        if not image_path.is_relative_to(path.resolve().parent):
            raise ValueError("Screenshot paths must belong to the manifest capture directory")
        if image_path.stat().st_size > 15_000_000:
            raise ValueError("Individual screenshot exceeds 15 MB")
        data = image_path.read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n") or hashlib.sha256(
            data
        ).hexdigest() != shot.get("sha256"):
            raise ValueError("Screenshot bytes do not match the captured PNG evidence")
        images.append(data)
        shots.append(
            {
                **{
                    key: shot.get(key)
                    for key in (
                        "label",
                        "state",
                        "width",
                        "height",
                        "image_width",
                        "image_height",
                        "sha256",
                    )
                },
                "revision": label,
                "image_index": offset + len(images) - 1,
            }
        )
    if sum(map(len, images)) > 30_000_000 or len(images) > 32:
        raise ValueError("Review supports at most 32 screenshots and 30 MB per manifest")
    return images, {
        "images": shots,
        "capture_checks": manifest.get("viewports"),
        "limits": manifest.get("limitations"),
        "source_revision": manifest.get("source_revision"),
        "source_revision_verified": False,
    }


async def review_evidence(
    *,
    manifest_path: Path,
    goal: str,
    provider_name: str,
    model: str,
    effort: str,
    threshold: float,
    baseline_path: Path | None = None,
    auth_mode: str = "subscription",
) -> dict:
    # Lazy import keeps the mechanical toolkit independent of automation startup.
    from frontend_design_loop_core.mcp_code_server import _VISION_SCORE_SYSTEM

    if provider_name not in {"codex_cli", "claude_cli", "opencode_cli"} or not model.strip():
        raise ValueError("Choose an explicit native provider and model")
    if not 0 <= threshold <= 10:
        raise ValueError("threshold must be in 0..10")
    images, candidate = _load(manifest_path, "candidate", 0)
    baseline = None
    if baseline_path:
        more, baseline = _load(baseline_path, "baseline", len(images))
        images += more
    adapter = ProviderFactory.get(provider_name, load_config())
    response = await adapter.complete_with_vision(
        [
            Message(role="system", content=_VISION_SCORE_SYSTEM),
            Message(
                role="user",
                content=f"GOAL\n{goal}\n\nLABELED EVIDENCE\n"
                + json.dumps({"candidate": candidate, "baseline": baseline}),
            ),
        ],
        model=model,
        images=images,
        reasoning_profile=effort,
        auth_mode=auth_mode,
        prompt_role="vision_score",
        timeout_s=300,
    )
    report = validate_visual_report(extract_json_strict(response.content))
    for view in candidate["capture_checks"] or []:
        for name, check in view.get("checks", {}).items():
            if (
                name in {"interactions", "http", "console", "images", "navigation", "overflow"}
                and check.get("status") == "failed"
            ):
                report["blockers"].append(f"Captured {name} check failed at {view.get('label')}")
    if baseline and report.get("baseline_comparison") == "worse":
        report["blockers"].append("Reviewer found a baseline regression")
    passed, score = visual_verdict(report, threshold)
    result = {
        "report": report,
        "eligible": passed,
        "score": score,
        "threshold": threshold,
        "manifest_path": str(manifest_path.resolve()),
        "execution": (response.raw_response or {}).get("execution", {}),
    }
    output = manifest_path.parent / "review.json"
    temporary = output.with_suffix(".json.new")
    temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    return result
