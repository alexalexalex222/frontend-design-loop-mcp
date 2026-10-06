"""Responsive screenshots with labeled, hashed evidence and focused browser checks."""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from design_toolkit.tools.context import redact_sensitive_text
from design_toolkit.tools.preview import validate_local_url

DEFAULT_VIEWPORTS = [
    {"label": "mobile", "width": 375, "height": 812},
    {"label": "tablet", "width": 768, "height": 1024},
    {"label": "desktop", "width": 1440, "height": 900},
]


def _viewports(values: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    values = DEFAULT_VIEWPORTS if values is None else values
    if not 1 <= len(values) <= 8:
        raise ValueError("Provide 1..8 viewports")
    seen = set()
    result = []
    for item in values:
        label = str(item.get("label", "desktop"))
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", label) or label in seen:
            raise ValueError(
                "Viewport labels must be unique safe filenames (letters, digits, _ and -)"
            )
        width, height = int(item.get("width", 1440)), int(item.get("height", 900))
        if not (200 <= width <= 4096 and 200 <= height <= 4096):
            raise ValueError("Viewport dimensions must be in 200..4096")
        result.append({"label": label, "width": width, "height": height})
        seen.add(label)
    return result


async def _interaction(page: Any, step: dict[str, Any], timeout_ms: int) -> dict[str, Any]:
    action = step.get("action")
    selector = step.get("selector")
    if (
        action not in {"click", "fill", "press", "expect_visible", "expect_text"}
        or not isinstance(selector, str)
        or not selector
    ):
        raise ValueError(
            "Interaction requires a selector and click/fill/press/expect_visible/expect_text action"
        )
    target = page.locator(selector)
    if action == "click":
        await target.click(timeout=timeout_ms)
    elif action == "fill":
        await target.fill(str(step.get("value", "")), timeout=timeout_ms)
    elif action == "press":
        await target.press(str(step.get("value", "Enter")), timeout=timeout_ms)
    else:
        await target.wait_for(state="visible", timeout=timeout_ms)
        if action == "expect_text":
            if "value" not in step:
                raise ValueError("expect_text requires a value")
            from playwright.async_api import expect

            await expect(target).to_contain_text(str(step["value"]), timeout=timeout_ms)
    return {"action": action, "selector": selector, "status": "passed"}


async def capture_evidence(
    *,
    url: str,
    out_dir: Path,
    viewports: list[dict[str, Any]] | None = None,
    timeout_ms: int = 30_000,
    full_page: bool = True,
    interactions: list[dict[str, Any]] | None = None,
    evidence_label: str = "candidate",
    source_revision: str | None = None,
    asset_policy: str = "public_assets",
) -> dict[str, Any]:
    origin = validate_local_url(url)
    if asset_policy not in {"same_origin", "public_assets"}:
        raise ValueError("asset_policy must be same_origin or public_assets")
    dimensions = _viewports(viewports)
    if timeout_ms <= 0 or timeout_ms > 120_000:
        raise ValueError("timeout_ms must be in 1..120000")
    steps = interactions or []
    for step in steps:
        if (
            not isinstance(step, dict)
            or step.get("action") not in {"click", "fill", "press", "expect_visible", "expect_text"}
            or not isinstance(step.get("selector"), str)
            or not step["selector"]
            or (step["action"] == "expect_text" and "value" not in step)
        ):
            raise ValueError(
                "Each interaction needs a supported action, nonempty selector, and value for expect_text"
            )
    if len(steps) > 30:
        raise ValueError("At most 30 focused interaction steps per viewport")
    from playwright.async_api import async_playwright

    # A fresh directory preserves baseline and previously preferred states.
    capture_id = uuid.uuid4().hex
    capture_dir = out_dir.resolve() / capture_id
    capture_dir.mkdir(parents=True, exist_ok=False)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "capture_id": capture_id,
        "evidence_label": evidence_label,
        "source_revision": source_revision,
        "source_revision_verified": False,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "url": url,
        "asset_policy": asset_policy,
        "screenshots": [],
        "viewports": [],
        "limitations": [
            "Source revision is a caller-supplied label, not a verified tree snapshot.",
            "Screenshots do not establish visual quality, accessibility, factual accuracy, or improvement.",
            "Interaction actions attest only to the requested steps and assertions.",
            "Overflow checks detect horizontal document overflow, not every clipped component.",
            "Document navigation and writes stay on the requested loopback origin. Public GET assets are allowed only when asset_policy=public_assets.",
            "Console observations cover only these captured states; sensitive text is redacted heuristically.",
        ],
    }
    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch()
        except Exception as exc:
            raise RuntimeError(
                "Chromium launch failed. Run frontend-design-loop-setup in this Python environment."
            ) from exc
        try:
            for viewport in dimensions:
                page = await browser.new_page(
                    viewport={k: viewport[k] for k in ("width", "height")}
                )
                console_errors: list[str] = []
                navigation_errors: list[str] = []
                failed_requests: list[dict[str, str]] = []
                blocked_requests: list[str] = []
                page.on(
                    "requestfailed",
                    lambda request: (
                        failed_requests.append(
                            {
                                "url": redact_sensitive_text(request.url)[:1000],
                                "failure": str(request.failure)[:500],
                            }
                        )
                        if len(failed_requests) < 50
                        else None
                    ),
                )

                def record_error(message: str) -> None:
                    if len(console_errors) < 50:
                        console_errors.append(redact_sensitive_text(message)[:2000])

                page.on("pageerror", lambda error: record_error(str(error)))
                page.on(
                    "console",
                    lambda message: (
                        record_error(message.text)
                        if message.type == "error" and "ERR_BLOCKED_BY_CLIENT" not in message.text
                        else None
                    ),
                )

                async def local_documents(route: Any) -> None:
                    request = route.request
                    parsed = urlsplit(request.url)
                    try:
                        validate_local_url(request.url, expected_origin=origin)
                        allowed = True
                    except ValueError:
                        allowed = (
                            asset_policy == "public_assets"
                            and request.method in {"GET", "HEAD"}
                            and request.resource_type
                            in {"image", "font", "stylesheet", "script", "media"}
                            and parsed.scheme == "https"
                            and not parsed.username
                            and not parsed.password
                        ) or (
                            parsed.scheme in {"data", "blob"}
                            and request.resource_type != "document"
                        )
                    if not allowed:
                        blocked_requests.append(redact_sensitive_text(request.url)[:1000])
                        if request.resource_type == "document":
                            navigation_errors.append(
                                "Blocked document navigation outside the requested origin"
                            )
                        await route.abort("blockedbyclient")
                        return
                    await route.continue_()

                await page.route("**/*", local_documents)
                checks: dict[str, Any] = {"interactions": {"status": "not_run", "steps": []}}
                record: dict[str, Any] = {**viewport, "checks": checks}
                try:
                    response = await page.goto(
                        url, wait_until="domcontentloaded", timeout=timeout_ms
                    )
                    checks["http"] = {
                        "status": "failed" if response and response.status >= 400 else "passed",
                        "status_code": response.status if response else None,
                    }
                    validate_local_url(page.url, expected_origin=origin)
                    readiness = await page.evaluate("""async () => {
                        const settled = Promise.all([document.fonts.ready, ...Array.from(document.images).map(
                            image => image.complete ? Promise.resolve() : new Promise(resolve => {
                                image.addEventListener('load', resolve, {once:true});
                                image.addEventListener('error', resolve, {once:true});
                            }))]);
                        return await Promise.race([settled.then(() => 'ready'),
                            new Promise(resolve => setTimeout(() => resolve('timeout'), 3000))]);
                    }""")
                    checks["readiness"] = {
                        "status": "passed" if readiness == "ready" else "uncertain",
                        "fonts_and_images": readiness,
                    }
                    await page.wait_for_timeout(150)
                    document_height = await page.evaluate("document.documentElement.scrollHeight")
                    capture_full = full_page and document_height <= 20000
                    if full_page and not capture_full:
                        manifest["limitations"].append(
                            f"{viewport['label']}: page exceeds 20000px; viewport captures only."
                        )
                    initial = capture_dir / f"{viewport['label']}.png"
                    # Playwright's default caret hiding mutates input styles;
                    # React can observe those mutations during hydration.
                    await page.screenshot(
                        path=str(initial), full_page=capture_full, timeout=timeout_ms, caret="initial"
                    )
                    manifest["screenshots"].append(
                        _shot(initial, viewport, "initial", capture_full)
                    )
                    if full_page and document_height > viewport["height"] * 1.5:
                        fold = capture_dir / f"{viewport['label']}-viewport.png"
                        await page.screenshot(path=str(fold), full_page=False, timeout=timeout_ms, caret="initial")
                        manifest["screenshots"].append(
                            _shot(fold, viewport, "initial_viewport", False)
                        )
                    if steps:
                        checks["interactions"]["status"] = "passed"
                        for step in steps:
                            try:
                                entry = await _interaction(page, step, timeout_ms)
                                validate_local_url(page.url, expected_origin=origin)
                                if navigation_errors:
                                    raise ValueError(navigation_errors[-1])
                            except Exception as exc:
                                entry = {
                                    "action": step.get("action"),
                                    "selector": step.get("selector"),
                                    "status": "failed",
                                    "error": redact_sensitive_text(str(exc))[:2000],
                                }
                                checks["interactions"]["status"] = "failed"
                                checks["interactions"]["steps"].append(entry)
                                break
                            checks["interactions"]["steps"].append(entry)
                        capture_full = (
                            full_page
                            and await page.evaluate("document.documentElement.scrollHeight")
                            <= 20000
                        )
                        final = capture_dir / f"{viewport['label']}-interaction.png"
                        await page.screenshot(
                            path=str(final), full_page=capture_full, timeout=timeout_ms, caret="initial"
                        )
                        manifest["screenshots"].append(
                            _shot(final, viewport, "after_interactions", capture_full)
                        )
                    overflow = await page.evaluate(
                        "({documentWidth: document.documentElement.scrollWidth, viewportWidth: innerWidth})"
                    )
                    checks["overflow"] = {
                        "status": "failed"
                        if overflow["documentWidth"] > overflow["viewportWidth"] + 1
                        else "passed",
                        **overflow,
                    }
                    broken_images = await page.evaluate(
                        "Array.from(document.images).filter(i => i.complete && !i.naturalWidth).map(i => i.src)"
                    )
                    checks["images"] = {
                        "status": "failed" if broken_images else "passed",
                        "broken": [redact_sensitive_text(value)[:1000] for value in broken_images],
                    }
                    checks["requests"] = {
                        "status": "failed"
                        if any(item["url"] not in blocked_requests for item in failed_requests)
                        else "uncertain"
                        if blocked_requests
                        else "passed",
                        "failed": failed_requests,
                        "blocked": blocked_requests,
                    }
                    checks["console"] = {
                        "status": "failed" if console_errors else "passed",
                        "errors": list(console_errors),
                    }
                    checks["navigation"] = {
                        "status": "failed" if navigation_errors else "passed",
                        "errors": list(navigation_errors),
                    }
                    record["status"] = (
                        "failed"
                        if any(c["status"] == "failed" for c in checks.values())
                        else "passed"
                    )
                except Exception as exc:
                    record.update(status="error", error=redact_sensitive_text(str(exc))[:2000])
                    for name in ("console", "navigation", "overflow"):
                        checks.setdefault(name, {"status": "not_run"})
                finally:
                    manifest["viewports"].append(record)
                    await page.close()
        finally:
            await browser.close()
    statuses = [record["status"] for record in manifest["viewports"]]
    manifest["status"] = (
        "error" if "error" in statuses else "failed" if "failed" in statuses else "passed"
    )
    manifest_path = capture_dir / "manifest.json"
    manifest["manifest_path"] = str(manifest_path)
    manifest["out_dir"] = str(capture_dir)
    temporary = manifest_path.with_suffix(".json.new")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, manifest_path)
    return manifest


def _shot(path: Path, viewport: dict, state: str, full_page: bool) -> dict[str, Any]:
    data = path.read_bytes()
    image_width, image_height = struct.unpack(">II", data[16:24])
    return {
        **viewport,
        "image_width": image_width,
        "image_height": image_height,
        "state": state,
        "path": str(path),
        "mime_type": "image/png",
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "full_page": full_page,
    }


async def capture_screenshots(**kwargs: Any) -> list[dict[str, Any]]:
    return (await capture_evidence(**kwargs))["screenshots"]


async def screenshot_to_bytes(path: Path) -> bytes:
    return path.read_bytes()


async def screenshots_to_bytes(paths: list[Path]) -> list[bytes]:
    return [path.read_bytes() for path in paths]
