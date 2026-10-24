"""Interactive gate cards (Approve / Edit / Reject).

Each card validates human input *before* resuming the graph so mistakes are
shown inline instead of failing inside a node. On a valid action the card
stores a resume command in ``st.session_state`` and triggers a rerun; app.py
then streams the graph with that command.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st
import yaml

from agents.common import to_yaml
from config import MAX_HEAL_ATTEMPTS, MAX_REJECTIONS_PER_GATE
from execution.assertion_guard import parse_errors
from graph.gates import GateInputError, validate_test_cases
from schemas import Interpretation


def _resume(value: dict[str, Any]) -> None:
    st.session_state["command"] = {"type": "resume", "value": value}
    st.rerun()


def _rejections_left(values: dict, gate: str) -> int:
    return MAX_REJECTIONS_PER_GATE - int((values.get("gate_rejections") or {}).get(gate, 0))


def _reject_caption(values: dict, gate: str) -> str:
    left = _rejections_left(values, gate)
    if left <= 0:
        return "⚠️ Regeneration limit reached — rejecting now **ends the run**."
    return f"Rejections left that trigger regeneration: {left}"


# --------------------------------------------------------------------- Gate 0
def gate0_card(values: dict, rev: int) -> None:
    interp = values.get("interpretation") or {}
    with st.container(border=True):
        st.subheader("✋ Gate 0 — Review the interpretation")
        st.caption(
            "**Approve** accepts it as generated. **Apply edits & approve** uses the YAML below. "
            "**Reject** regenerates it with your feedback. Answers to ambiguities are passed to every later agent."
        )
        answers: dict[str, str] = {}
        if interp.get("ambiguities"):
            st.markdown("**Answer the ambiguities** (blank = use the suggested resolution)")
            for amb in interp["ambiguities"]:
                answers[amb["id"]] = st.text_input(
                    f"{amb['id']}: {amb['question']}",
                    value=amb.get("suggested_resolution", ""),
                    help=amb.get("impact") or None,
                    key=f"g0_amb_{amb['id']}_{rev}",
                )
        edited_yaml = st.text_area("Interpretation (YAML, editable)", value=to_yaml(interp), height=360, key=f"g0_yaml_{rev}")
        feedback = st.text_area("Feedback (required to reject)", key=f"g0_fb_{rev}", height=80)
        st.caption(_reject_caption(values, "gate0"))

        c1, c2, c3 = st.columns(3)
        if c1.button("✅ Approve", type="primary", key=f"g0_ok_{rev}", width="stretch"):
            _resume({"action": "approve", "ambiguity_answers": answers})
        if c2.button("✏️ Apply edits & approve", key=f"g0_edit_{rev}", width="stretch"):
            try:
                data = yaml.safe_load(edited_yaml) or {}
                validated = Interpretation.model_validate(data).model_dump()
                if not validated["requirements"]:
                    raise ValueError("at least one requirement is required")
            except Exception as exc:
                st.error(f"Invalid interpretation: {exc}")
            else:
                _resume({"action": "edit", "interpretation": validated, "ambiguity_answers": answers})
        if c3.button("❌ Reject", key=f"g0_rej_{rev}", width="stretch"):
            if not feedback.strip():
                st.error("Please explain what is wrong before rejecting.")
            else:
                _resume({"action": "reject", "feedback": feedback})


# --------------------------------------------------------------------- Gate 1
_LIST_FIELDS = ("requirement_ids", "preconditions", "steps", "expected_results")


def _cases_to_frame(cases: list[dict]) -> pd.DataFrame:
    rows = []
    for tc in cases:
        rows.append(
            {
                "id": tc["id"],
                "title": tc.get("title", ""),
                "scenario_id": tc.get("scenario_id", ""),
                "requirement_ids": ", ".join(tc.get("requirement_ids") or []),
                "priority": tc.get("priority", "medium"),
                "preconditions": "\n".join(tc.get("preconditions") or []),
                "steps": "\n".join(tc.get("steps") or []),
                "expected_results": "\n".join(tc.get("expected_results") or []),
                "test_data": "\n".join(f"{k}={v}" for k, v in (tc.get("test_data") or {}).items()),
            }
        )
    return pd.DataFrame(rows, columns=["id", "title", "scenario_id", "requirement_ids", "priority", *_LIST_FIELDS[1:], "test_data"])


def _frame_to_cases(frame: pd.DataFrame) -> list[dict]:
    cases = []
    for _, row in frame.fillna("").iterrows():
        if not str(row["id"]).strip() and not str(row["title"]).strip():
            continue  # blank row added in the editor
        test_data = {}
        for line in str(row["test_data"]).splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                test_data[key.strip()] = value.strip()
        cases.append(
            {
                "id": str(row["id"]).strip().upper(),
                "title": str(row["title"]).strip(),
                "scenario_id": str(row["scenario_id"]).strip(),
                "requirement_ids": [r.strip().upper() for r in str(row["requirement_ids"]).split(",") if r.strip()],
                "priority": str(row["priority"]).strip() or "medium",
                "preconditions": [s.strip() for s in str(row["preconditions"]).splitlines() if s.strip()],
                "steps": [s.strip() for s in str(row["steps"]).splitlines() if s.strip()],
                "expected_results": [s.strip() for s in str(row["expected_results"]).splitlines() if s.strip()],
                "test_data": test_data,
            }
        )
    return cases


def gate1_card(values: dict, rev: int) -> None:
    cases = values.get("test_cases") or []
    uncovered = (values.get("coverage_matrix") or {}).get("uncovered", [])
    gate2_feedback = ((values.get("gate_feedback") or {}).get("gate2") or {}).get("feedback")
    with st.container(border=True):
        st.subheader("✋ Gate 1 — Review test cases and coverage")
        if gate2_feedback:
            st.info(f"Sent back from Gate 2 with feedback: {gate2_feedback}")
        st.caption(
            "**Approve** freezes the test cases for code generation. **Apply edits** saves your changes and "
            "rebuilds the coverage matrix (you approve afterwards). **Generate for uncovered** asks the Test Case "
            "Generator for the highlighted gaps only. **Reject** regenerates with your feedback."
        )
        mode = st.radio("Edit as", ["Table", "YAML"], horizontal=True, key=f"g1_mode_{rev}")
        if mode == "Table":
            st.caption("Multi-line cells (steps, expected results…) use one line per item; test data uses `name=value` lines.")
            edited_frame = st.data_editor(
                _cases_to_frame(cases),
                num_rows="dynamic",
                hide_index=True,
                key=f"g1_table_{rev}",
                column_config={
                    "priority": st.column_config.SelectboxColumn(options=["high", "medium", "low"]),
                    **{c: st.column_config.TextColumn(width="large") for c in ("steps", "expected_results")},
                },
            )
            edited_yaml = None
        else:
            edited_yaml = st.text_area("Test cases (YAML)", value=to_yaml(cases), height=420, key=f"g1_yaml_{rev}")
            edited_frame = None

        feedback = st.text_area("Feedback (required to reject)", key=f"g1_fb_{rev}", height=80)
        target = st.radio(
            "On reject, regenerate",
            ["test_cases", "scenarios"],
            format_func=lambda t: "Test cases only" if t == "test_cases" else "Scenarios and test cases",
            horizontal=True,
            key=f"g1_target_{rev}",
        )
        st.caption(_reject_caption(values, "gate1"))

        c1, c2, c3, c4 = st.columns(4)
        if c1.button("✅ Approve", type="primary", key=f"g1_ok_{rev}", width="stretch"):
            _resume({"action": "approve"})
        if c2.button("✏️ Apply edits", key=f"g1_edit_{rev}", width="stretch"):
            try:
                raw = _frame_to_cases(edited_frame) if edited_frame is not None else (yaml.safe_load(edited_yaml) or [])
                if not isinstance(raw, list):
                    raise GateInputError("YAML must be a list of test cases")
                validated = validate_test_cases(raw)
            except Exception as exc:
                st.error(f"Invalid test cases: {exc}")
            else:
                _resume({"action": "edit", "test_cases": validated})
        if c3.button(
            f"➕ Generate for uncovered ({len(uncovered)})",
            key=f"g1_gap_{rev}",
            disabled=not uncovered,
            width="stretch",
        ):
            _resume({"action": "fill_gaps"})
        if c4.button("❌ Reject", key=f"g1_rej_{rev}", width="stretch"):
            if not feedback.strip():
                st.error("Please explain what is wrong before rejecting.")
            else:
                _resume({"action": "reject", "feedback": feedback, "target": target})


# --------------------------------------------------------- Run confirmation
def confirm_run_card(values: dict, rev: int) -> None:
    with st.container(border=True):
        st.subheader("🔍 Review generated code before it runs")
        st.caption(
            "The module above was written by an LLM and will execute on this machine with pytest. "
            "Review it, then run. Turn on **Auto-run generated code** in the sidebar to skip this check. "
            f"Healed versions inside the self-repair loop (max {MAX_HEAL_ATTEMPTS}) run automatically."
        )
        c1, c2 = st.columns(2)
        if c1.button("▶️ Run tests", type="primary", key=f"cr_run_{rev}", width="stretch"):
            _resume({"action": "run"})
        if c2.button("⏹️ Cancel run", key=f"cr_cancel_{rev}", width="stretch"):
            _resume({"action": "cancel"})


# --------------------------------------------------------------------- Gate 2
def gate2_card(values: dict, rev: int) -> None:
    attempts = values.get("execution_results") or []
    last = attempts[-1] if attempts else {}
    passed = last.get("status") == "passed"
    failing = sorted(
        {t.get("test_case_id") or t["name"] for t in last.get("tests", []) if t["outcome"] in ("failed", "error")}
    )
    with st.container(border=True):
        st.subheader("✋ Gate 2 — Approve the baseline")
        if passed:
            st.success(f"Green baseline after {len(attempts)} run(s).")
        else:
            st.error(
                f"Tests still failing after {len(attempts)} run(s) and {values.get('heal_attempts', 0)} heal attempt(s). "
                f"Failing: {', '.join(failing) or 'n/a'}. Real failures (assertion/server/environment) are never auto-healed."
            )
        st.caption(
            "**Approve** exports the suite"
            + ("" if passed else " and records the failing tests as known failures")
            + ". **Apply edit & re-run** runs your edited code (human edits may change assertions). "
            "**Reject** sends it back to Gate 1 or ends the run."
        )
        edited_code = st.text_area("Test module (editable)", value=values.get("generated_code", ""), height=420, key=f"g2_code_{rev}")
        feedback = st.text_area("Feedback (required to reject)", key=f"g2_fb_{rev}", height=80)
        target = st.radio(
            "On reject",
            ["gate1", "end"],
            format_func=lambda t: "Back to Gate 1 (regenerate code)" if t == "gate1" else "End the run",
            horizontal=True,
            key=f"g2_target_{rev}",
        )
        st.caption(_reject_caption(values, "gate2"))

        c1, c2, c3 = st.columns(3)
        approve_label = "✅ Approve baseline" if passed else "⚠️ Approve with known failures"
        if c1.button(approve_label, type="primary", key=f"g2_ok_{rev}", width="stretch"):
            _resume({"action": "approve"})
        if c2.button("✏️ Apply edit & re-run", key=f"g2_edit_{rev}", width="stretch"):
            error = parse_errors(edited_code)
            if error:
                st.error(error)
            elif edited_code == values.get("generated_code"):
                st.warning("No changes to apply.")
            else:
                _resume({"action": "edit", "code": edited_code})
        if c3.button("❌ Reject", key=f"g2_rej_{rev}", width="stretch"):
            if not feedback.strip():
                st.error("Please explain what is wrong before rejecting.")
            else:
                _resume({"action": "reject", "feedback": feedback, "target": target})


GATE_CARDS = {
    "gate0": ("interpretation", gate0_card),
    "gate1": ("test_cases", gate1_card),
    "confirm_run": ("code", confirm_run_card),
    "gate2": ("baseline", gate2_card),
}
