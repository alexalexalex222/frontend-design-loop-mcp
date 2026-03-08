#!/usr/bin/env python3
"""Smoke native CLI vision providers against a common screenshot payload."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from frontend_design_loop_core import mcp_code_server


PROVIDER_DEFAULTS: dict[str, str] = {
    "claude_cli": "claude-opus-4-6",
    "codex_cli": "gpt-5.4",
    "gemini_cli": "gemini-3.1-pro-preview",
    "kilo_cli": "kilo/minimax/minimax-m2.5:free",
    "droid_cli": "custom:minimax/minimax-m2.5:free",
    "opencode_cli": "opencode/minimax-m2.5-free",
}


def _make_demo_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "magick",
        "-size",
        "1400x900",
        "xc:#08121c",
        "-fill",
        "#15f0b5",
        "-draw",
        "rectangle 80,110 1320,780",
        "-fill",
        "#08121c",
        "-draw",
        "rectangle 96,126 1304,764",
        "-fill",
        "#e8f2ff",
        "-font",
        "Helvetica-Bold",
        "-pointsize",
        "46",
        "-annotate",
        "+120+210",
        "frontend design loop native cli vision smoke",
        "-fill",
        "#7de4ff",
        "-font",
        "Helvetica",
        "-pointsize",
        "28",
        "-annotate",
        "+120+280",
        "structured screenshot payload for real provider verification",
        "-fill",
        "#9ee7c4",
        "-draw",
        "rectangle 120,340 560,430",
        "-draw",
        "rectangle 120,470 820,560",
        "-draw",
        "rectangle 900,340 1270,650",
        "-fill",
        "#08121c",
        "-font",
        "Helvetica-Bold",
        "-pointsize",
        "24",
        "-annotate",
        "+145+394",
        "broken=false target",
        "-annotate",
        "+145+524",
        "expect json only",
        "-annotate",
        "+935+500",
        "signature panel",
        str(path),
    ]
    subprocess.run(cmd, check=True)


async def _run_provider(provider_name: str, model: str, image_bytes: bytes) -> dict[str, Any]:
    report = await mcp_code_server._vision_eval(
        images=[image_bytes],
        goal="Decide whether the screenshot is a real coherent page and score it conservatively.",
        threshold=7.0,
        provider_name=provider_name,
        model=model,
        min_confidence=0.85,
        kind="ui",
    )
    return report


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--providers",
        nargs="+",
        default=list(PROVIDER_DEFAULTS.keys()),
        help="Providers to smoke",
    )
    parser.add_argument(
        "--out-dir",
        default="out/native-cli-vision-smokes",
        help="Output directory for artifacts",
    )
    parser.add_argument(
        "--image",
        default="",
        help="Optional existing PNG path. If omitted, a demo image is generated.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    out_dir = (repo_root / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.image:
        image_path = Path(args.image).expanduser().resolve()
    else:
        image_path = out_dir / "smoke_input.png"
        _make_demo_image(image_path)

    image_bytes = image_path.read_bytes()
    results: list[dict[str, Any]] = []

    for provider_name in args.providers:
        model = PROVIDER_DEFAULTS.get(provider_name)
        if not model:
            results.append(
                {
                    "provider": provider_name,
                    "ok": False,
                    "error": "no default model configured",
                }
            )
            continue

        try:
            report = await _run_provider(provider_name, model, image_bytes)
            payload = {
                "provider": provider_name,
                "model": model,
                "ok": True,
                "report": report,
            }
        except Exception as exc:  # noqa: BLE001
            payload = {
                "provider": provider_name,
                "model": model,
                "ok": False,
                "error": str(exc),
            }

        results.append(payload)
        (out_dir / f"{provider_name}.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    summary = {
        "cwd": str(repo_root),
        "image": str(image_path),
        "results": results,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if all(item.get("ok") for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
