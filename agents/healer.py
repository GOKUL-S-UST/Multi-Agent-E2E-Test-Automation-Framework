"""Healer Agent: repairs mechanical failures without touching assertions.

Every candidate is checked by :mod:`execution.assertion_guard`; a candidate
that changes what a test validates, removes tests, adds skips or edits passing
tests is rejected and the previous code is kept.
"""

from __future__ import annotations

import json

from agents.code_generator import format_site_context
from agents.common import extract_python_block, target_fields, text_after_code, to_yaml, truncate
from execution.assertion_guard import check_heal
from execution.failure_classifier import CATEGORY_LABELS, is_healable
from llm import LLMClient
from prompts import load_prompt


def _failures_text(tests: list[dict]) -> str:
    blocks = []
    for t in tests:
        if t["outcome"] not in ("failed", "error"):
            continue
        healable = is_healable(t.get("category", ""))
        blocks.append(
            f"### {t['name']} ({t.get('test_case_id') or 'n/a'})\n"
            f"Classification: {CATEGORY_LABELS.get(t.get('category', ''), t.get('category'))} - "
            f"{t.get('category_reason', '')}\n"
            f"Action: {'HEAL' if healable else 'DO NOT CHANGE (real failure, escalated to a human)'}\n"
            f"Message: {t.get('message', '')}\n"
            f"Details:\n{truncate(t.get('details', ''), 2500)}"
        )
    return "\n\n".join(blocks) or "(none)"


def _failure_context_text(tests: list[dict]) -> str:
    contexts = {t["name"]: t["failure_context"] for t in tests if t.get("failure_context")}
    if not contexts:
        return "(not captured)"
    return truncate(json.dumps(contexts, indent=2), 12000)


def _previous_attempts_text(heal_history: list[dict]) -> str:
    if not heal_history:
        return ""
    summary = [
        {"heal": h["heal"], "status": h["status"], "changes": h.get("changes", ""), "violations": h.get("violations", [])}
        for h in heal_history
    ]
    return "\nPrevious heal attempts (do not repeat rejected approaches):\n" + to_yaml(summary)


def run(state: dict, llm: LLMClient) -> dict:
    attempts = state.get("execution_results", [])
    last = attempts[-1]
    code = state.get("generated_code", "")
    passed = [t["name"] for t in last["tests"] if t["outcome"] == "passed"]
    heal_number = int(state.get("heal_attempts", 0)) + 1

    system, user = load_prompt("healer").render(
        code=code,
        passed_tests=", ".join(passed) or "(none)",
        failures=_failures_text(last["tests"]),
        failure_context=_failure_context_text(last["tests"]),
        site_context=format_site_context(state.get("site_context")),
        previous_attempts=_previous_attempts_text(state.get("heal_history", [])),
        **target_fields(state),
    )
    response = llm.generate_text(system, user)
    candidate = extract_python_block(response)
    changes = text_after_code(response)
    guard = check_heal(code, candidate, state.get("assertion_baseline") or {}, passed)

    record = {
        "heal": heal_number,
        "after_attempt": last["attempt"],
        "status": "applied" if guard.ok else "rejected",
        "changes": changes,
        "violations": guard.violations,
        "candidate_code": candidate,
    }
    update: dict = {
        "heal_attempts": heal_number,
        "heal_history": [*state.get("heal_history", []), record],
    }
    if guard.ok:
        update.update(
            generated_code=candidate,
            code_version=int(state.get("code_version", 0)) + 1,
            code_origin="healer",
        )
    return update
