"""Deterministic orchestrator.

The orchestrator is a graph node (so its decision can be recorded in
``history``) followed by a single conditional edge that simply follows the
recorded ``next_node``. Routing depends only on what is populated and what has
been approved in the state - no LLM call.
"""

from __future__ import annotations

from datetime import datetime, timezone

from langgraph.graph import END

from config import MAX_HEAL_ATTEMPTS

# Node names
INTERPRETER = "interpreter"
GATE0 = "gate0"
SCENARIO_GENERATOR = "scenario_generator"
TEST_CASE_GENERATOR = "test_case_generator"
COVERAGE_BUILDER = "coverage_builder"
GATE1 = "gate1"
SITE_EXPLORER = "site_explorer"
CODE_GENERATOR = "code_generator"
CONFIRM_RUN = "confirm_run"
EXECUTOR = "executor"
HEALER = "healer"
GATE2 = "gate2"
FINALIZE = "finalize"

ROUTABLE_NODES = [
    INTERPRETER, GATE0, SCENARIO_GENERATOR, TEST_CASE_GENERATOR, COVERAGE_BUILDER, GATE1,
    SITE_EXPLORER, CODE_GENERATOR, CONFIRM_RUN, EXECUTOR, HEALER, GATE2, FINALIZE,
]


def decide_next(state: dict) -> tuple[str, str]:
    """Return ``(next_node, reason)``. ``END`` terminates the run."""
    if state.get("halted_reason"):
        return END, f"Run halted: {state['halted_reason']}"
    if state.get("final_artifacts"):
        return END, "Baseline approved and exported - Phase 1 complete"
    if not (state.get("raw_requirement") or "").strip():
        return END, "No requirement provided"

    if not state.get("interpretation"):
        return INTERPRETER, "No interpretation yet"
    if not state.get("interpretation_approved"):
        return GATE0, "Interpretation awaits human approval (Gate 0)"

    if not state.get("scenarios"):
        return SCENARIO_GENERATOR, "Interpretation approved; scenarios missing"
    if not state.get("test_cases"):
        return TEST_CASE_GENERATOR, "Scenarios ready; test cases missing"
    if state.get("gap_fill_requested"):
        uncovered = (state.get("coverage_matrix") or {}).get("uncovered", [])
        return TEST_CASE_GENERATOR, f"Reviewer requested test cases for uncovered requirements: {', '.join(uncovered)}"
    if state.get("coverage_matrix") is None:
        return COVERAGE_BUILDER, "Test cases changed; coverage matrix out of date"
    if not state.get("test_cases_approved"):
        return GATE1, "Test cases and coverage await human approval (Gate 1)"

    if state.get("site_context") is None:
        return SITE_EXPLORER, "Test cases approved; capturing target page snapshot for code generation"
    if not state.get("generated_code"):
        return CODE_GENERATOR, "Generating Playwright code from approved test cases"
    if state.get("baseline_approved"):
        return FINALIZE, "Baseline approved (Gate 2); exporting suite"

    attempts = state.get("execution_results") or []
    last = attempts[-1] if attempts else None
    if last is None or last.get("code_version") != state.get("code_version"):
        if not state.get("code_run_confirmed"):
            return CONFIRM_RUN, "Generated code must be confirmed before it runs locally"
        label = "Original run" if not attempts else f"Re-run after heal {state.get('heal_attempts', 0)}"
        return EXECUTOR, f"{label}: executing code version {state.get('code_version')}"

    if last.get("status") == "passed":
        return GATE2, "All tests passed; green baseline awaits approval (Gate 2)"
    heals = int(state.get("heal_attempts", 0))
    if heals >= MAX_HEAL_ATTEMPTS:
        return GATE2, f"Tests still failing after {heals} heal attempts; escalating to human (Gate 2)"
    if not last.get("healable"):
        return GATE2, "Failures are not mechanical (assertion/server/environment); escalating to human (Gate 2)"
    return HEALER, f"Mechanical failures detected; heal attempt {heals + 1} of {MAX_HEAL_ATTEMPTS}"


def orchestrator_node(state: dict) -> dict:
    next_node, reason = decide_next(state)
    history = list(state.get("history") or [])
    history.append(
        {
            "step": len(history) + 1,
            "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "from": state.get("current_stage", "start"),
            "next": "END" if next_node == END else next_node,
            "reason": reason,
        }
    )
    return {"next_node": next_node, "history": history, "current_stage": "done" if next_node == END else next_node}


def route(state: dict) -> str:
    """Conditional edge: follow the decision recorded by the orchestrator node."""
    return state.get("next_node") or END
