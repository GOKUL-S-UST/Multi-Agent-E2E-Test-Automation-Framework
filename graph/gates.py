"""Human approval gates, implemented with LangGraph ``interrupt()``.

Each gate pauses the graph and hands control to the UI. The UI resumes the
graph with ``Command(resume={"action": ..., ...})``. Gates only record the
human decision in state; the orchestrator decides what happens next.
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from agents.common import ensure_unique_ids
from config import MAX_REJECTIONS_PER_GATE
from execution.assertion_guard import extract_assertion_signatures, parse_errors
from schemas import Interpretation, test_case_from_state, test_case_to_state


class GateInputError(ValueError):
    """The human input supplied when resuming a gate is invalid."""


def _without(feedback: dict | None, *gates: str) -> dict:
    return {k: v for k, v in (feedback or {}).items() if k not in gates}


def _register_rejection(state: dict, gate: str) -> tuple[dict[str, int], str | None]:
    counts = dict(state.get("gate_rejections") or {})
    counts[gate] = counts.get(gate, 0) + 1
    halted = None
    if counts[gate] > MAX_REJECTIONS_PER_GATE:
        halted = f"{gate.upper()} rejected {counts[gate]} times (limit {MAX_REJECTIONS_PER_GATE} regenerations)"
    return counts, halted


def _feedback_text(decision: dict) -> str:
    feedback = (decision.get("feedback") or "").strip()
    if not feedback:
        raise GateInputError("A rejection requires feedback explaining what is wrong.")
    return feedback


# --------------------------------------------------------------------- Gate 0
def gate0_node(state: dict) -> dict:
    decision: dict[str, Any] = interrupt({"gate": "gate0", "title": "Gate 0 - Approve interpretation"})
    action = decision.get("action")
    answers = {k: v for k, v in (decision.get("ambiguity_answers") or {}).items() if (v or "").strip()}

    if action == "approve":
        return {
            "interpretation_approved": True,
            "ambiguity_answers": answers,
            "gate_feedback": _without(state.get("gate_feedback"), "gate0"),
        }
    if action == "edit":
        try:
            edited = Interpretation.model_validate(decision.get("interpretation") or {}).model_dump()
        except Exception as exc:
            raise GateInputError(f"Edited interpretation is invalid: {exc}") from exc
        if not edited["requirements"]:
            raise GateInputError("The interpretation must contain at least one requirement.")
        ensure_unique_ids(edited["requirements"], "REQ")
        return {
            "interpretation": edited,
            "interpretation_approved": True,
            "ambiguity_answers": answers,
            "gate_feedback": _without(state.get("gate_feedback"), "gate0"),
        }
    if action == "reject":
        feedback = _feedback_text(decision)
        counts, halted = _register_rejection(state, "gate0")
        return {
            "interpretation": None,
            "interpretation_approved": False,
            "ambiguity_answers": {},
            "gate_rejections": counts,
            "halted_reason": halted,
            "gate_feedback": {
                **(state.get("gate_feedback") or {}),
                "gate0": {"feedback": feedback, "rejected": state.get("interpretation")},
            },
        }
    raise GateInputError(f"Unknown Gate 0 action: {action!r}")


# --------------------------------------------------------------------- Gate 1
def validate_test_cases(raw: list[dict]) -> list[dict]:
    try:
        cases = [test_case_to_state(test_case_from_state(tc)) for tc in raw]
    except Exception as exc:
        raise GateInputError(f"Edited test cases are invalid: {exc}") from exc
    if not cases:
        raise GateInputError("At least one test case is required.")
    ids = [tc["id"] for tc in cases]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise GateInputError(f"Duplicate test case ids: {', '.join(duplicates)}")
    return cases


def gate1_node(state: dict) -> dict:
    decision: dict[str, Any] = interrupt({"gate": "gate1", "title": "Gate 1 - Approve test cases and coverage"})
    action = decision.get("action")

    if action == "approve":
        return {"test_cases_approved": True, "gate_feedback": _without(state.get("gate_feedback"), "gate1")}
    if action == "edit":
        # Edits are saved and the coverage matrix is rebuilt; the gate is shown
        # again so the reviewer approves what the new coverage looks like.
        return {"test_cases": validate_test_cases(decision.get("test_cases") or []), "coverage_matrix": None}
    if action == "fill_gaps":
        if not (state.get("coverage_matrix") or {}).get("uncovered"):
            raise GateInputError("There are no uncovered requirements to fill.")
        return {"gap_fill_requested": True}
    if action == "reject":
        feedback = _feedback_text(decision)
        target = decision.get("target", "test_cases")
        if target not in ("test_cases", "scenarios"):
            raise GateInputError(f"Unknown Gate 1 rejection target: {target!r}")
        counts, halted = _register_rejection(state, "gate1")
        rejected = [{"id": tc["id"], "title": tc.get("title")} for tc in state.get("test_cases", [])]
        update: dict[str, Any] = {
            "test_cases": [],
            "coverage_matrix": None,
            "test_cases_approved": False,
            "gate_rejections": counts,
            "halted_reason": halted,
            "gate_feedback": {
                **(state.get("gate_feedback") or {}),
                "gate1": {"feedback": feedback, "target": target, "rejected": rejected},
            },
        }
        if target == "scenarios":
            update["scenarios"] = []
        return update
    raise GateInputError(f"Unknown Gate 1 action: {action!r}")


# ------------------------------------------------------- Run confirmation
def confirm_run_node(state: dict, config: RunnableConfig) -> dict:
    """Safety check before LLM-generated code executes on this machine."""
    if (config.get("configurable") or {}).get("auto_run"):
        return {"code_run_confirmed": True}
    decision: dict[str, Any] = interrupt({"gate": "confirm_run", "title": "Review generated code before running"})
    if decision.get("action") == "run":
        return {"code_run_confirmed": True}
    if decision.get("action") == "cancel":
        return {"halted_reason": "Execution cancelled by the reviewer before running generated code"}
    raise GateInputError(f"Unknown run confirmation action: {decision.get('action')!r}")


# --------------------------------------------------------------------- Gate 2
def _failing_test_case_ids(state: dict) -> list[str]:
    attempts = state.get("execution_results") or []
    if not attempts:
        return []
    return sorted(
        {t.get("test_case_id") or t["name"] for t in attempts[-1]["tests"] if t["outcome"] in ("failed", "error")}
    )


def gate2_node(state: dict) -> dict:
    decision: dict[str, Any] = interrupt({"gate": "gate2", "title": "Gate 2 - Approve baseline"})
    action = decision.get("action")

    if action == "approve":
        return {
            "baseline_approved": True,
            "known_failures": _failing_test_case_ids(state),
            "gate_feedback": _without(state.get("gate_feedback"), "gate2"),
        }
    if action == "edit":
        code = decision.get("code") or ""
        error = parse_errors(code)
        if error:
            raise GateInputError(f"Edited code does not parse: {error}")
        # A human edit is authoritative: it becomes the new assertion baseline.
        return {
            "generated_code": code,
            "code_version": int(state.get("code_version", 0)) + 1,
            "code_origin": "human",
            "code_run_confirmed": True,
            "assertion_baseline": extract_assertion_signatures(code),
        }
    if action == "reject":
        feedback = _feedback_text(decision)
        counts, halted = _register_rejection(state, "gate2")
        if decision.get("target") == "end":
            halted = halted or "Baseline rejected by the reviewer"
        return {
            "test_cases_approved": False,
            "generated_code": "",
            "code_run_confirmed": False,
            "execution_results": [],
            "heal_attempts": 0,
            "heal_history": [],
            "assertion_baseline": {},
            "gate_rejections": counts,
            "halted_reason": halted,
            "gate_feedback": {**(state.get("gate_feedback") or {}), "gate2": {"feedback": feedback}},
        }
    raise GateInputError(f"Unknown Gate 2 action: {action!r}")
