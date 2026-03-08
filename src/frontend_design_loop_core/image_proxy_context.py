"""Deterministic screenshot proxy extraction for text-only model lanes."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


def _run_capture(args: list[str], timeout_s: float = 30.0) -> str:
    try:
        proc = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except Exception as exc:  # noqa: BLE001
        return f"<unavailable: {exc}>"
    output = (proc.stdout or "").strip()
    if output:
        return output
    err = (proc.stderr or "").strip()
    if err:
        return f"<unavailable: {err}>"
    return "<unavailable>"


def _ocr_text(path: Path) -> str:
    swift_source = """
import Foundation
import Vision
import AppKit

let url = URL(fileURLWithPath: CommandLine.arguments[1])
guard let image = NSImage(contentsOf: url) else {
    fputs("<unavailable: image load failed>\\n", stderr)
    exit(1)
}
var rect = CGRect(origin: .zero, size: image.size)
guard let cg = image.cgImage(forProposedRect: &rect, context: nil, hints: nil) else {
    fputs("<unavailable: cgImage conversion failed>\\n", stderr)
    exit(1)
}
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
let handler = VNImageRequestHandler(cgImage: cg, options: [:])
try handler.perform([request])
let observations = request.results ?? []
for obs in observations {
    if let top = obs.topCandidates(1).first {
        print(top.string)
    }
}
"""
    with tempfile.TemporaryDirectory(prefix="frontend-design-loop-ocr-") as tmp_dir_str:
        script_path = Path(tmp_dir_str) / "ocr.swift"
        script_path.write_text(swift_source, encoding="utf-8")
        output = _run_capture(["swift", str(script_path), str(path)], timeout_s=60.0)
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return "<none>"
    return "\n".join(lines[:20])


def build_visual_proxy_context(image_paths: list[Path]) -> str:
    sections: list[str] = []
    for idx, path in enumerate(image_paths, start=1):
        identify = _run_capture(
            [
                "magick",
                "identify",
                "-format",
                "width=%w height=%h colors=%k mean=%[fx:mean] std=%[fx:standard_deviation]",
                str(path),
            ]
        )
        palette = _run_capture(
            [
                "magick",
                str(path),
                "-resize",
                "24x24",
                "-colors",
                "6",
                "-unique-colors",
                "txt:-",
            ]
        )
        palette_lines = [line.strip() for line in palette.splitlines()[1:7] if line.strip()]
        ocr = _ocr_text(path)
        section = [
            f"IMAGE {idx}: {path.name}",
            f"FILE_BYTES: {path.stat().st_size}",
            f"IMAGE_STATS: {identify}",
            "OCR_TEXT:",
            ocr,
            "DOMINANT_COLORS:",
            "\n".join(palette_lines) if palette_lines else "<none>",
        ]
        sections.append("\n".join(section))
    return "\n\n".join(sections).strip()
