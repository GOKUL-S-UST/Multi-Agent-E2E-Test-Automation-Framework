"""Heuristic classification of Playwright/pytest failures.

Phase 1 only heals *mechanical* problems (locator drift, waits, navigation,
bugs in the generated code). Assertion mismatches and server/environment
errors are surfaced to the human at Gate 2 instead of being "fixed".
"""

from __future__ import annotations

import re

MECHANICAL = "mechanical"
CODE_ERROR = "code_error"
ASSERTION = "assertion"
SERVER = "server"
ENVIRONMENT = "environment"
UNKNOWN = "unknown"

HEALABLE_CATEGORIES = frozenset({MECHANICAL, CODE_ERROR, UNKNOWN})

CATEGORY_LABELS = {
    MECHANICAL: "Mechanical (locator / wait / navigation)",
    CODE_ERROR: "Generated code error",
    ASSERTION: "Assertion failure (real)",
    SERVER: "Server error (real)",
    ENVIRONMENT: "Environment / setup",
    UNKNOWN: "Unknown",
}

_ENVIRONMENT_PATTERNS = [
    (r"Executable doesn't exist|playwright install", "Playwright browser not installed - run `python -m playwright install chromium`"),
    (r"ERR_NAME_NOT_RESOLVED|ERR_INTERNET_DISCONNECTED|ERR_CONNECTION_REFUSED|ERR_CONNECTION_RESET|ERR_PROXY", "Target site unreachable from this machine"),
    (r"KeyError: '(TARGET_USERNAME|TARGET_PASSWORD)'", "Credentials missing - set the site's username/password variables in .env"),
    (r"run timed out", "Test run exceeded the execution timeout"),
]
_SERVER_PATTERNS = [
    (r"\b5\d\d\b[^\n]{0,40}(Internal Server Error|Bad Gateway|Service Unavailable|Gateway Timeout)", "Server returned a 5xx response"),
    (r"ERR_HTTP_RESPONSE_CODE_FAILURE|ERR_EMPTY_RESPONSE", "Server returned an error response"),
]
_CODE_ERROR_PATTERNS = [
    (r"\b(SyntaxError|IndentationError|NameError|ImportError|ModuleNotFoundError|AttributeError|TypeError|UnboundLocalError)\b", "Python error in the generated code"),
    (r"fixture '[^']+' not found", "Unknown pytest fixture used"),
    (r"ERROR collecting|collection error|no tests ran", "Test module could not be collected"),
]
_LOCATOR_DRIFT_IN_ASSERTION = r"element\(s\) not found|Actual value: None|resolved to 0 elements|<element\(s\) not found>"
_MECHANICAL_PATTERNS = [
    (r"strict mode violation", "Locator matched more than one element"),
    (r"TimeoutError|Timeout \d+ms exceeded", "Timed out waiting for an element or navigation"),
    (r"not attached to the DOM|element is not (visible|enabled|stable)|intercepts pointer events", "Element not actionable"),
    (r"Target (page, context or browser )?(has been )?closed|Navigation failed|net::ERR_ABORTED", "Navigation problem"),
]


def classify_failure(text: str) -> tuple[str, str]:
    """Return ``(category, reason)`` for a failure message/traceback."""
    text = text or ""
    for pattern, reason in _ENVIRONMENT_PATTERNS:
        if re.search(pattern, text):
            return ENVIRONMENT, reason
    for pattern, reason in _SERVER_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return SERVER, reason

    is_assertion = "AssertionError" in text or re.search(r"Locator expected|Page expected|expected to", text)
    if is_assertion:
        if re.search(_LOCATOR_DRIFT_IN_ASSERTION, text):
            return MECHANICAL, "Assertion target element not found (likely locator drift)"
        if re.search(r"strict mode violation", text):
            return MECHANICAL, "Assertion locator matched more than one element"
        return ASSERTION, "Observed value differs from the expected result"

    for pattern, reason in _CODE_ERROR_PATTERNS:
        if re.search(pattern, text):
            return CODE_ERROR, reason
    for pattern, reason in _MECHANICAL_PATTERNS:
        if re.search(pattern, text):
            return MECHANICAL, reason
    return UNKNOWN, "Unrecognised failure"


def is_healable(category: str) -> bool:
    return category in HEALABLE_CATEGORIES
