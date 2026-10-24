import pytest

from execution.failure_classifier import classify_failure, is_healable


@pytest.mark.parametrize(
    "text, category",
    [
        ("playwright._impl._errors.TimeoutError: Locator.click: Timeout 30000ms exceeded.", "mechanical"),
        ("Error: strict mode violation: get_by_text('Add') resolved to 6 elements", "mechanical"),
        (
            "AssertionError: Locator expected to be visible\nActual value: None\nError: element(s) not found",
            "mechanical",
        ),
        ("AssertionError: Locator expected to have text 'Products'\nActual value: Login", "assertion"),
        ("NameError: name 'login' is not defined", "code_error"),
        ("E       fixture 'browser_page' not found", "code_error"),
        ("Page.goto: net::ERR_NAME_NOT_RESOLVED at https://nope.invalid/", "environment"),
        ("BrowserType.launch: Executable doesn't exist at /x/chrome", "environment"),
        ("KeyError: 'TARGET_PASSWORD'", "environment"),
        ("Response status 503 Service Unavailable", "server"),
        ("something odd happened", "unknown"),
    ],
)
def test_classification(text, category):
    assert classify_failure(text)[0] == category


def test_healable_categories():
    assert is_healable("mechanical") and is_healable("code_error") and is_healable("unknown")
    assert not is_healable("assertion") and not is_healable("server") and not is_healable("environment")
