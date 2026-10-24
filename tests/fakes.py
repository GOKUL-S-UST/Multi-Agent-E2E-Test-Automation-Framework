"""Deterministic stand-ins for the LLM used by framework tests."""

from __future__ import annotations

from schemas import Interpretation, ScenarioSet, TestCaseSet

GOOD_CODE = '''\
import os
from playwright.sync_api import Page, expect


def test_tc_001(page: Page):
    """TC-001 Successful login"""
    page.goto("/")
    page.get_by_placeholder("Username").fill(os.environ["TARGET_USERNAME"])
    page.get_by_role("button", name="Login").click()
    # ASSERTIONS-BEGIN TC-001
    expect(page.get_by_text("Products")).to_be_visible()
    # ASSERTIONS-END TC-001


def test_tc_002(page: Page):
    """TC-002 Wrong password"""
    page.goto("/")
    page.locator("#login").click()
    # ASSERTIONS-BEGIN TC-002
    expect(page.locator(".error")).to_have_text("Bad credentials")
    # ASSERTIONS-END TC-002
'''

HEALED_CODE = GOOD_CODE.replace('page.locator("#login").click()', 'page.get_by_role("button", name="Login").click()').replace(
    'expect(page.locator(".error"))', 'expect(page.get_by_test_id("error"))'
)

CHEATING_CODE = GOOD_CODE.replace('to_have_text("Bad credentials")', 'to_be_visible()')


class FakeLLM:
    def __init__(self, heal_responses: list[str] | None = None):
        self.calls: list[tuple[str, str]] = []
        self.heal_responses = list(heal_responses or [f"```python\n{HEALED_CODE}```\nCHANGES:\n- fixed locator"])

    def generate_structured(self, schema, system, user):
        self.calls.append((schema.__name__, user))
        if schema is Interpretation:
            return Interpretation.model_validate(
                {
                    "summary": "Login",
                    "requirements": [
                        {"id": "REQ-001", "description": "Valid users can log in"},
                        {"id": "REQ-002", "description": "Invalid password shows an error"},
                        {"id": "REQ-003", "description": "Locked users are blocked"},
                    ],
                    "ambiguities": [{"id": "AMB-001", "question": "Which error text?"}],
                }
            )
        if schema is ScenarioSet:
            return ScenarioSet.model_validate(
                {
                    "scenarios": [
                        {"id": "SC-001", "title": "Login ok", "category": "functional", "requirement_ids": ["REQ-001"]},
                        {"id": "SC-002", "title": "Bad pwd", "category": "negative", "requirement_ids": ["REQ-002"]},
                    ]
                }
            )
        if schema is TestCaseSet:
            if "GAP FILL MODE" in user:
                return TestCaseSet.model_validate(
                    {"test_cases": [{"id": "TC-001", "title": "Locked user", "requirement_ids": ["REQ-003"]}]}
                )
            return TestCaseSet.model_validate(
                {
                    "test_cases": [
                        {
                            "id": "TC-001",
                            "title": "Successful login",
                            "requirement_ids": ["REQ-001"],
                            "steps": ["Open page", "Log in"],
                            "expected_results": ["Products visible"],
                            "test_data": [{"name": "username", "value": "<TARGET_USERNAME>"}],
                        },
                        {"id": "TC-002", "title": "Wrong password", "requirement_ids": ["REQ-002"]},
                    ]
                }
            )
        raise AssertionError(f"unexpected schema {schema}")

    def generate_text(self, system, user):
        if "Healer Agent" in system:
            self.calls.append(("heal", user))
            return self.heal_responses.pop(0) if self.heal_responses else f"```python\n{HEALED_CODE}```"
        self.calls.append(("code", user))
        return f"Here you go\n```python\n{GOOD_CODE}```"
