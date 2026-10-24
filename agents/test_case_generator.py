"""Test Case Generator Agent: scenarios -> concrete test cases.

Two modes:
- full: generate the complete set (first run or after a Gate 1 rejection)
- gap fill: generate additional cases only for requirements the coverage
  matrix reports as uncovered, appended to the existing set
"""

from __future__ import annotations

from agents.common import (
    ensure_unique_ids,
    feedback_block,
    format_id,
    interpretation_context,
    max_id_number,
    target_fields,
    to_yaml,
)
from llm import LLMClient
from prompts import load_prompt
from schemas import TestCaseSet, test_case_to_state

_FULL_MODE = "Generate the complete set of test cases for all scenarios."


def _gap_mode_instructions(state: dict) -> str:
    uncovered = (state.get("coverage_matrix") or {}).get("uncovered", [])
    existing = [
        {"id": tc["id"], "title": tc.get("title"), "requirement_ids": tc.get("requirement_ids")}
        for tc in state.get("test_cases", [])
    ]
    return (
        "GAP FILL MODE: the existing test cases below leave these requirements uncovered: "
        f"{', '.join(uncovered)}.\n"
        "Generate ONLY new test cases that cover those requirements. Do not repeat existing ones.\n"
        f"Existing test cases:\n{to_yaml(existing)}"
    )


def run(state: dict, llm: LLMClient) -> dict:
    gap_mode = bool(state.get("gap_fill_requested")) and bool(state.get("test_cases"))
    system, user = load_prompt("test_case_generator").render(
        interpretation=interpretation_context(state),
        scenarios=to_yaml(state.get("scenarios", [])),
        mode_instructions=_gap_mode_instructions(state) if gap_mode else _FULL_MODE,
        feedback="" if gap_mode else feedback_block(state, "gate1"),
        **target_fields(state),
    )
    result = llm.generate_structured(TestCaseSet, system, user)
    new_cases = [test_case_to_state(tc) for tc in result.test_cases]

    if gap_mode:
        existing = list(state.get("test_cases", []))
        next_number = max_id_number(tc["id"] for tc in existing) + 1
        for offset, tc in enumerate(new_cases):
            tc["id"] = format_id("TC", next_number + offset)
        test_cases = existing + new_cases
    else:
        if not new_cases:
            raise ValueError("Test Case Generator returned no test cases.")
        test_cases = ensure_unique_ids(new_cases, "TC")

    return {"test_cases": test_cases, "coverage_matrix": None, "gap_fill_requested": False}
