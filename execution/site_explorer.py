"""Captures a compact snapshot of the target site's start page.

The Code Generator uses it to choose locators that actually exist instead of
guessing. Invoked in a subprocess (``python -m execution.site_explorer``) so
Playwright never runs inside the Streamlit process.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any

from config import PROJECT_ROOT

SNAPSHOT_LIMIT = 15000


def _capture(url: str, timeout_ms: int) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass  # busy pages never go idle; the DOM is good enough
            snapshot = page.locator("body").aria_snapshot(timeout=10000)
            links = page.eval_on_selector_all(
                "a[href]",
                "els => els.slice(0, 60).map(e => ({text: (e.innerText || '').trim().slice(0, 80), href: e.getAttribute('href')}))",
            )
            return {
                "url": page.url,
                "title": page.title(),
                "aria_snapshot": snapshot[:SNAPSHOT_LIMIT],
                "truncated": len(snapshot) > SNAPSHOT_LIMIT,
                "links": [link for link in links if link.get("href")],
            }
        finally:
            browser.close()


def explore(url: str, timeout_seconds: int = 60) -> dict[str, Any]:
    """Run the capture out-of-process. Never raises; errors are returned in the dict."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "execution.site_explorer", "--url", url],
            cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return {"url": url, "error": f"Site exploration timed out after {timeout_seconds}s"}
    lines = [line for line in (proc.stdout or "").splitlines() if line.strip()]
    if proc.returncode != 0 or not lines:
        return {"url": url, "error": (proc.stderr or proc.stdout or "unknown error").strip()[-2000:]}
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return {"url": url, "error": "Could not parse site explorer output"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture an ARIA snapshot of a web page")
    parser.add_argument("--url", required=True)
    parser.add_argument("--timeout-ms", type=int, default=30000)
    args = parser.parse_args()
    try:
        result = _capture(args.url, args.timeout_ms)
    except Exception as exc:
        print(json.dumps({"url": args.url, "error": f"{type(exc).__name__}: {exc}"}))
        sys.exit(0)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
