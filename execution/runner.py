"""Runs a generated Playwright module with pytest in an isolated subprocess.

Running out-of-process keeps Playwright's sync API away from Streamlit's
event loop (a hard failure on Windows) and lets us enforce a timeout. Results
are read from a JUnit XML report and mapped back to test case ids.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from agents.common import test_function_name, truncate
from execution.failure_classifier import ENVIRONMENT, classify_failure, is_healable

TEST_FILE_NAME = "test_generated.py"
REPORT_NAME = "report.xml"
_LOG_LIMIT = 20000
_DETAIL_LIMIT = 4000

# Captures URL, title and ARIA snapshot of the page when a test fails so the
# Healer can pick locators that exist at the moment of failure.
FAILURE_CONTEXT_CONFTEST = '''\
import json
import re
from pathlib import Path

import pytest

_CONTEXT_DIR = Path(__file__).parent / "failure_context"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.failed:
        return
    page = getattr(item, "funcargs", {}).get("page")
    if page is None:
        return
    data = {"test": item.name}
    try:
        data["url"] = page.url
        data["title"] = page.title()
    except Exception as exc:  # page may be closed
        data["page_error"] = str(exc)
    try:
        data["aria_snapshot"] = page.locator("body").aria_snapshot(timeout=5000)[:15000]
    except Exception as exc:
        data["aria_snapshot_error"] = str(exc)
    _CONTEXT_DIR.mkdir(exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", item.name)
    (_CONTEXT_DIR / f"{safe}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
'''


def resolve_credentials(target_site: dict[str, Any]) -> dict[str, str]:
    """Map the selected site's credential env vars onto TARGET_USERNAME/PASSWORD."""
    env: dict[str, str] = {}
    user_var, pass_var = target_site.get("username_env"), target_site.get("password_env")
    if user_var and os.getenv(user_var):
        env["TARGET_USERNAME"] = os.environ[user_var]
    if pass_var and os.getenv(pass_var):
        env["TARGET_PASSWORD"] = os.environ[pass_var]
    return env


def _test_case_lookup(test_case_ids: list[str]) -> dict[str, str]:
    return {test_function_name(tc_id): tc_id for tc_id in test_case_ids}


def _match_test_case(name: str, lookup: dict[str, str]) -> str | None:
    base = name.split("[", 1)[0]
    if base in lookup:
        return lookup[base]
    for fn, tc_id in sorted(lookup.items(), key=lambda kv: -len(kv[0])):
        if base.startswith(fn + "_"):
            return tc_id
    return None


def _collect_files(directory: Path, pattern: str) -> list[Path]:
    return sorted(directory.rglob(pattern)) if directory.exists() else []


def parse_junit(report_path: Path, test_case_ids: list[str], run_dir: Path) -> list[dict[str, Any]]:
    if not report_path.exists():
        return []
    try:
        root = ET.parse(report_path).getroot()
    except ET.ParseError:
        return []

    lookup = _test_case_lookup(test_case_ids)
    screenshots = _collect_files(run_dir / "artifacts", "*.png")
    contexts_dir = run_dir / "failure_context"
    results = []
    for case in root.iter("testcase"):
        name = case.get("name", "")
        outcome, message, details = "passed", "", ""
        for tag in ("failure", "error", "skipped"):
            node = case.find(tag)
            if node is not None:
                outcome = {"failure": "failed", "error": "error", "skipped": "skipped"}[tag]
                message = node.get("message", "") or ""
                details = node.text or ""
                break
        entry: dict[str, Any] = {
            "name": name,
            "test_case_id": _match_test_case(name, lookup),
            "outcome": outcome,
            "duration": float(case.get("time", 0) or 0),
            "message": truncate(message, 1000),
            "details": truncate(details, _DETAIL_LIMIT),
        }
        if outcome in ("failed", "error"):
            category, reason = classify_failure(f"{message}\n{details}")
            entry.update(category=category, category_reason=reason)
            safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
            context_file = contexts_dir / f"{safe}.json"
            if context_file.exists():
                try:
                    entry["failure_context"] = json.loads(context_file.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    pass
            slug = name.split("[", 1)[0].replace("_", "-").lower()
            entry["screenshots"] = [str(p) for p in screenshots if slug in str(p).lower().replace("_", "-")]
        results.append(entry)
    return results


def run_suite(
    code: str,
    *,
    base_url: str,
    run_dir: Path,
    test_case_ids: list[str],
    credentials: dict[str, str] | None = None,
    headed: bool = False,
    browser: str = "chromium",
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    """Execute ``code`` and return a structured result (no ``attempt`` metadata)."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / TEST_FILE_NAME).write_text(code, encoding="utf-8")
    (run_dir / "conftest.py").write_text(FAILURE_CONTEXT_CONFTEST, encoding="utf-8")
    # A local ini stops pytest from picking up the framework's own pytest.ini.
    (run_dir / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    report_path = run_dir / REPORT_NAME

    cmd = [
        sys.executable, "-m", "pytest", TEST_FILE_NAME,
        "--base-url", base_url,
        "--browser", browser,
        "--screenshot", "only-on-failure",
        "--output", "artifacts",
        f"--junitxml={REPORT_NAME}",
        "-p", "no:cacheprovider",
        "-rfE", "--tb=short", "-q",
    ]
    if headed:
        cmd.append("--headed")

    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    env.pop("TARGET_USERNAME", None)
    env.pop("TARGET_PASSWORD", None)
    env.update(credentials or {})

    timed_out = False
    try:
        proc = subprocess.run(
            cmd, cwd=run_dir, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout_seconds,
        )
        returncode, logs = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode = -1
        out = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        logs = out + f"\n\nrun timed out after {timeout_seconds}s"

    tests = parse_junit(report_path, test_case_ids, run_dir)
    if not tests or timed_out:
        category, reason = classify_failure(logs)
        if timed_out:
            category, reason = ENVIRONMENT, "Test run exceeded the execution timeout"
        tests = tests + [{
            "name": "<test run>",
            "test_case_id": None,
            "outcome": "error",
            "duration": 0.0,
            "message": f"pytest exited with code {returncode} without usable results" if not timed_out else "run timed out",
            "details": truncate(logs[-_DETAIL_LIMIT:], _DETAIL_LIMIT),
            "category": category,
            "category_reason": reason,
            "screenshots": [],
        }]

    summary = {k: sum(1 for t in tests if t["outcome"] == k) for k in ("passed", "failed", "error", "skipped")}
    failing = [t for t in tests if t["outcome"] in ("failed", "error")]
    executed_ids = {t["test_case_id"] for t in tests if t["test_case_id"]}
    missing = [tc for tc in test_case_ids if tc not in executed_ids]

    if failing:
        # "error": nothing that maps to a test case ran (collection/setup failure)
        status = "failed" if executed_ids else "error"
    elif returncode == 0 and summary["passed"] > 0:
        status = "passed"
    else:
        status = "failed"

    return {
        "status": status,
        "returncode": returncode,
        "summary": summary,
        "tests": tests,
        "missing_test_cases": missing,
        "healable": any(is_healable(t.get("category", "")) for t in failing),
        "logs": truncate(logs, _LOG_LIMIT),
        "artifacts_dir": str(run_dir),
    }
