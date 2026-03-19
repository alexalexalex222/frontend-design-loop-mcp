"""capture_screenshots - Playwright-based screenshot capture across viewports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from design_toolkit.utils import log

DEFAULT_VIEWPORTS = [
    {"label": "mobile", "width": 375, "height": 812},
    {"label": "tablet", "width": 768, "height": 1024},
    {"label": "desktop", "width": 1440, "height": 900},
]


def _playwright_install_hint(err: BaseException) -> str | None:
    msg = str(err or "")
    lower = msg.lower()
    triggers = [
        "executable doesn't exist",
        "executable does not exist",
        "download new browsers",
        "run the following command",
        "playwright install",
    ]
    if any(trigger in lower for trigger in triggers):
        return (
            "Playwright Chromium not found. Run: playwright install chromium\n"
            f"Original error: {msg}"
        )
    return None


async def capture_screenshots(
    *,
    url: str,
    out_dir: Path,
    viewports: list[dict[str, Any]] | None = None,
    timeout_ms: int = 30_000,
    full_page: bool = True,
) -> list[dict[str, Any]]:
    """Capture screenshots of a URL across viewports."""
    from playwright.async_api import async_playwright

    if viewports is None:
        viewports = DEFAULT_VIEWPORTS

    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch()
        except Exception as exc:
            hint = _playwright_install_hint(exc)
            if hint:
                raise RuntimeError(hint) from exc
            raise

        try:
            for viewport in viewports:
                label = str(viewport.get("label") or "desktop")
                width = int(viewport.get("width") or 1440)
                height = int(viewport.get("height") or 900)

                page = await browser.new_page(viewport={"width": width, "height": height})
                try:
                    await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                    await page.wait_for_timeout(250)

                    shot_path = out_dir / f"{label}.png"
                    await page.screenshot(path=str(shot_path), full_page=full_page)

                    results.append(
                        {
                            "label": label,
                            "path": str(shot_path),
                            "width": width,
                            "height": height,
                        }
                    )
                    log(f"Screenshot captured: {label} ({width}x{height})")
                finally:
                    await page.close()
        finally:
            await browser.close()

    return results


async def screenshot_to_bytes(path: Path) -> bytes:
    """Read a screenshot file as bytes."""
    return path.read_bytes()


async def screenshots_to_bytes(paths: list[Path]) -> list[bytes]:
    """Read multiple screenshot files as bytes."""
    return [path.read_bytes() for path in paths]
