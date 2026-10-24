"""Runs real Playwright tests against a tiny local site (skipped if no browser)."""

import functools
import http.server
import threading

import pytest

from execution.runner import run_suite
from execution.site_explorer import explore

PAGE = """<!doctype html><html><head><title>Mini Shop</title></head><body>
<h1>Mini Shop</h1>
<label for="user">Username</label><input id="user">
<button onclick="document.getElementById('msg').textContent='Welcome ' + document.getElementById('user').value">Login</button>
<p id="msg"></p>
</body></html>"""

SUITE = '''\
import os
from playwright.sync_api import Page, expect


def test_tc_001(page: Page):
    page.goto("/")
    page.get_by_label("Username").fill(os.environ["TARGET_USERNAME"])
    page.get_by_role("button", name="Login").click()
    # ASSERTIONS-BEGIN TC-001
    expect(page.locator("#msg")).to_have_text("Welcome alice")
    # ASSERTIONS-END TC-001


def test_tc_002(page: Page):
    page.goto("/")
    page.get_by_role("button", name="Sign in").click(timeout=1500)
    # ASSERTIONS-BEGIN TC-002
    expect(page.locator("#msg")).to_have_text("Welcome ")
    # ASSERTIONS-END TC-002


def test_tc_003(page: Page):
    page.goto("/")
    # ASSERTIONS-BEGIN TC-003
    expect(page.get_by_role("heading")).to_have_text("Other Shop", timeout=1500)
    # ASSERTIONS-END TC-003
'''


def _browser_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _browser_available(), reason="Playwright chromium not installed")


@pytest.fixture
def site(tmp_path):
    (tmp_path / "index.html").write_text(PAGE, encoding="utf-8")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_run_suite_classifies_results(site, tmp_path):
    result = run_suite(
        SUITE,
        base_url=site,
        run_dir=tmp_path / "run",
        test_case_ids=["TC-001", "TC-002", "TC-003", "TC-004"],
        credentials={"TARGET_USERNAME": "alice"},
        timeout_seconds=120,
    )
    by_id = {t["test_case_id"]: t for t in result["tests"]}
    assert result["status"] == "failed"
    assert by_id["TC-001"]["outcome"] == "passed"
    assert by_id["TC-002"]["category"] == "mechanical"
    assert "aria_snapshot" in by_id["TC-002"]["failure_context"]
    assert by_id["TC-003"]["category"] == "assertion"
    assert result["healable"] is True
    assert result["missing_test_cases"] == ["TC-004"]


def test_run_suite_reports_collection_errors(site, tmp_path):
    result = run_suite("def test_tc_001(page):\n    syntax error here\n", base_url=site,
                       run_dir=tmp_path / "run", test_case_ids=["TC-001"], timeout_seconds=120)
    assert result["status"] == "error", result["tests"]
    assert result["tests"][-1]["category"] == "code_error", result["tests"]
    assert result["healable"] is True


def test_site_explorer_captures_snapshot(site):
    data = explore(site)
    assert data.get("title") == "Mini Shop", data
    assert "Login" in data["aria_snapshot"]
