"""Playwright Code Generator Agent: approved test cases -> one pytest module."""

from __future__ import annotations

import re

from agents.common import (
    extract_python_block,
    feedback_block,
    target_fields,
    test_function_name,
    to_yaml,
    truncate,
)
from execution.assertion_guard import (
    extract_assertion_signatures,
    marker_test_case_ids,
    parse_errors,
    test_function_names,
)
from llm import LLMClient
from prompts import load_prompt

_FORBIDDEN = [
    (r"\btime\.sleep\(", "uses time.sleep"),
    (r"\.wait_for_timeout\(", "uses page.wait_for_timeout"),
    (r"\.goto\(\s*[\"']https?://", "hard-codes an absolute URL in page.goto (use relative paths)"),
    (r"pytest\.(skip|xfail)|mark\.(skip|xfail)", "skips or xfails tests"),
]


def format_site_context(site_context: dict | None) -> str:
    if not site_context:
        return "(not available)"
    if site_context.get("error"):
        return f"(could not capture the page: {truncate(site_context['error'], 500)})"
    links = to_yaml(site_context.get("links", [])[:40]) if site_context.get("links") else "(none)"
    return (
        f"URL: {site_context.get('url')}\nTitle: {site_context.get('title')}\n"
        f"ARIA snapshot:\n{site_context.get('aria_snapshot', '')}\n\nLinks:\n{links}"
    )


def validate_generated_code(code: str, test_case_ids: list[str]) -> list[str]:
    problems: list[str] = []
    error = parse_errors(code)
    if error:
        return [error]
    names = set(test_function_names(code))
    missing = [f"{tc} -> {test_function_name(tc)}" for tc in test_case_ids if test_function_name(tc) not in names]
    if missing:
        problems.append("Missing required test functions: " + ", ".join(missing))
    marked = marker_test_case_ids(code)
    unmarked = [tc for tc in test_case_ids if tc.upper() not in marked]
    if unmarked:
        problems.append("Missing '# ASSERTIONS-BEGIN/END <id>' blocks for: " + ", ".join(unmarked))
    for pattern, message in _FORBIDDEN:
        if re.search(pattern, code):
            problems.append(f"Code {message}")
    return problems


def run(state: dict, llm: LLMClient) -> dict:
    test_cases = state.get("test_cases", [])
    tc_ids = [tc["id"] for tc in test_cases]
    function_names = "\n".join(f"- {tc} -> {test_function_name(tc)}" for tc in tc_ids)
    system, user = load_prompt("code_generator").render(
        function_names=function_names,
        test_cases=to_yaml(test_cases),
        site_context=format_site_context(state.get("site_context")),
        feedback=feedback_block(state, "gate2", "Reviewer feedback on the previously generated code"),
        **target_fields(state),
    )

    code = extract_python_block(llm.generate_text(system, user))
    problems = validate_generated_code(code, tc_ids)
    if problems:
        retry_user = (
            f"{user}\n\nYour previous answer had these problems - fix ALL of them and return the full module:\n- "
            + "\n- ".join(problems)
            + f"\n\nPrevious answer:\n```python\n{code}```"
        )
        code = extract_python_block(llm.generate_text(system, retry_user))
        problems = validate_generated_code(code, tc_ids)

    return {
        "generated_code": code,
        "code_version": int(state.get("code_version", 0)) + 1,
        "code_origin": "generator",
        "code_warnings": problems,
        "code_run_confirmed": False,
        "assertion_baseline": extract_assertion_signatures(code),
        "execution_results": [],
        "heal_attempts": 0,
        "heal_history": [],
    }
