"""LangGraph state definition for the Phase 1 pipeline."""

from __future__ import annotations

from typing import Any, TypedDict


class PipelineState(TypedDict, total=False):
    # --- Input -------------------------------------------------------------
    raw_requirement: str
    requirement_source: str  # "text" or the uploaded file name
    target_site: dict[str, Any]  # TargetSite.to_dict()

    # --- Interpretation + Gate 0 ------------------------------------------
    # {summary, requirements, rules, entities, assumptions, ambiguities}
    interpretation: dict[str, Any] | None
    interpretation_approved: bool
    ambiguity_answers: dict[str, str]  # ambiguity id -> human answer

    # --- Scenarios / test cases / coverage + Gate 1 -----------------------
    scenarios: list[dict[str, Any]]
    # each: {id, title, scenario_id, requirement_ids, preconditions, steps,
    #        expected_results, test_data (dict), priority}
    test_cases: list[dict[str, Any]]
    # {by_requirement: {req_id: [tc_id]}, uncovered: [req_id],
    #  unknown_references: {tc_id: [req_id]}}
    coverage_matrix: dict[str, Any] | None
    test_cases_approved: bool
    gap_fill_requested: bool

    # --- Code generation + self-repair + Gate 2 ---------------------------
    site_context: dict[str, Any] | None  # page snapshot captured before codegen
    generated_code: str
    code_version: int  # bumped every time generated_code changes
    code_origin: str  # "generator" | "healer" | "human"
    code_warnings: list[str]  # validation problems left after generation
    code_run_confirmed: bool
    # test function name -> assertion signatures, captured at generation time;
    # the healer must preserve them (lightweight stand-in for the future hash lock)
    assertion_baseline: dict[str, list[str]]
    # each attempt: {attempt, label, code_version, code, status, summary, tests,
    #                logs, artifacts_dir, healable}
    execution_results: list[dict[str, Any]]
    heal_attempts: int
    heal_history: list[dict[str, Any]]
    baseline_approved: bool
    known_failures: list[str]
    final_artifacts: dict[str, Any] | None

    # --- Gate bookkeeping --------------------------------------------------
    # gate name -> {feedback, target?, rejected?}
    gate_feedback: dict[str, dict[str, Any]]
    gate_rejections: dict[str, int]
    halted_reason: str | None

    # --- Orchestration -----------------------------------------------------
    current_stage: str
    next_node: str
    history: list[dict[str, Any]]


def initial_state(raw_requirement: str, requirement_source: str, target_site: dict[str, Any]) -> PipelineState:
    return PipelineState(
        raw_requirement=raw_requirement,
        requirement_source=requirement_source,
        target_site=target_site,
        interpretation=None,
        interpretation_approved=False,
        ambiguity_answers={},
        scenarios=[],
        test_cases=[],
        coverage_matrix=None,
        test_cases_approved=False,
        gap_fill_requested=False,
        site_context=None,
        generated_code="",
        code_version=0,
        code_origin="",
        code_warnings=[],
        code_run_confirmed=False,
        assertion_baseline={},
        execution_results=[],
        heal_attempts=0,
        heal_history=[],
        baseline_approved=False,
        known_failures=[],
        final_artifacts=None,
        gate_feedback={},
        gate_rejections={},
        halted_reason=None,
        current_stage="start",
        next_node="",
        history=[],
    )
