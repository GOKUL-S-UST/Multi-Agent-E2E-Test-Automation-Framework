"""Read-only renderers for each pipeline stage.

These functions create no keyed widgets, so they can be re-rendered many times
in a single Streamlit run while the graph streams updates.
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from config import MAX_HEAL_ATTEMPTS
from execution.failure_classifier import CATEGORY_LABELS
from ui.theme import stepper_html

NODE_LABELS = {
    "orchestrator": "Orchestrator",
    "interpreter": "Interpreter Agent",
    "gate0": "Gate 0 (interpretation)",
    "scenario_generator": "Scenario Generator Agent",
    "test_case_generator": "Test Case Generator Agent",
    "coverage_builder": "Coverage Matrix Builder",
    "gate1": "Gate 1 (test cases)",
    "site_explorer": "Site Explorer",
    "code_generator": "Playwright Code Generator Agent",
    "confirm_run": "Run confirmation",
    "executor": "Playwright Runner",
    "healer": "Healer Agent",
    "gate2": "Gate 2 (baseline)",
    "finalize": "Export",
    "__end__": "END",
    "END": "END",
}

STAGES = [
    ("interpretation", "1 · Interpretation", {"interpreter", "gate0"}),
    ("scenarios", "2 · Scenarios", {"scenario_generator"}),
    ("test_cases", "3 · Test cases & coverage", {"test_case_generator", "coverage_builder", "gate1"}),
    ("code", "4 · Playwright code", {"site_explorer", "code_generator", "confirm_run"}),
    ("self_repair", "5 · Self-repair loop", {"executor", "healer"}),
    ("baseline", "6 · Baseline", {"gate2", "finalize"}),
]

STATUS_ICON = {"done": "✅", "active": "⏳", "waiting": "✋", "pending": "▫️", "halted": "⛔"}
OUTCOME_ICON = {"passed": "✅", "failed": "❌", "error": "💥", "skipped": "⏭️"}


def label(node: str | None) -> str:
    return NODE_LABELS.get(node or "", node or "")


def stage_status(values: dict, stage: str, pending_gate: str | None) -> str:
    current = values.get("current_stage")
    nodes = next(n for key, _, n in STAGES if key == stage)
    if pending_gate in nodes:
        return "waiting"
    done = {
        "interpretation": bool(values.get("interpretation_approved")),
        "scenarios": bool(values.get("scenarios")) and bool(values.get("interpretation_approved")),
        "test_cases": bool(values.get("test_cases_approved")),
        "code": bool(values.get("generated_code")) and bool(values.get("code_run_confirmed")),
        "self_repair": bool(values.get("execution_results")) and current in {"gate2", "finalize", "done"},
        "baseline": bool(values.get("final_artifacts")),
    }[stage]
    if done:
        return "done"
    if values.get("halted_reason"):
        return "halted" if current in nodes else "pending"
    return "active" if current in nodes else "pending"


def render_stepper(values: dict, pending_gate: str | None) -> None:
    steps = [(key, stage_status(values, key, pending_gate) if values else "pending") for key, _, _ in STAGES]
    st.html(stepper_html(steps))


def _df(rows: list[dict], columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame([{c: r.get(c) for c in columns} for r in rows], columns=columns)


def _join(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return "; ".join(f"{k}={v}" for k, v in value.items())
    return "" if value is None else str(value)


# ----------------------------------------------------------------- stages
def render_interpretation(values: dict) -> None:
    interp = values.get("interpretation")
    if not interp:
        st.caption("Waiting for the Interpreter Agent…")
        return
    if values.get("interpretation_approved"):
        st.success("Approved at Gate 0")
    if interp.get("summary"):
        st.markdown(f"**Summary:** {interp['summary']}")
    tabs = st.tabs(
        [
            f"Requirements ({len(interp.get('requirements', []))})",
            f"Rules ({len(interp.get('rules', []))})",
            f"Entities ({len(interp.get('entities', []))})",
            f"Assumptions ({len(interp.get('assumptions', []))})",
            f"Ambiguities ({len(interp.get('ambiguities', []))})",
        ]
    )
    with tabs[0]:
        st.dataframe(_df(interp.get("requirements", []), ["id", "description", "priority", "source_excerpt"]), hide_index=True)
    with tabs[1]:
        rules = [{**r, "requirement_ids": _join(r.get("requirement_ids"))} for r in interp.get("rules", [])]
        st.dataframe(_df(rules, ["id", "description", "requirement_ids"]), hide_index=True)
    with tabs[2]:
        entities = [{**e, "attributes": _join(e.get("attributes"))} for e in interp.get("entities", [])]
        st.dataframe(_df(entities, ["name", "description", "attributes"]), hide_index=True)
    with tabs[3]:
        st.dataframe(_df(interp.get("assumptions", []), ["id", "description"]), hide_index=True)
    with tabs[4]:
        answers = values.get("ambiguity_answers") or {}
        rows = [{**a, "human_answer": answers.get(a.get("id"), "")} for a in interp.get("ambiguities", [])]
        st.dataframe(_df(rows, ["id", "question", "impact", "suggested_resolution", "human_answer"]), hide_index=True)


def render_scenarios(values: dict) -> None:
    scenarios = values.get("scenarios") or []
    if not scenarios:
        st.caption("Waiting for the Scenario Generator Agent…")
        return
    counts = pd.Series([s.get("category") for s in scenarios]).value_counts()
    st.caption(" · ".join(f"{cat}: {n}" for cat, n in counts.items()))
    rows = [{**s, "requirement_ids": _join(s.get("requirement_ids"))} for s in scenarios]
    st.dataframe(_df(rows, ["id", "title", "category", "priority", "requirement_ids", "description"]), hide_index=True)


def render_test_cases(values: dict) -> None:
    cases = values.get("test_cases") or []
    if not cases:
        st.caption("Waiting for the Test Case Generator Agent…")
        return
    if values.get("test_cases_approved"):
        st.success("Approved at Gate 1")
    rows = [
        {
            "id": tc["id"],
            "title": tc.get("title"),
            "scenario": tc.get("scenario_id"),
            "requirements": _join(tc.get("requirement_ids")),
            "priority": tc.get("priority"),
            "steps": len(tc.get("steps") or []),
            "expected results": len(tc.get("expected_results") or []),
        }
        for tc in cases
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    with st.expander("Test case details"):
        for tc in cases:
            st.markdown(f"**{tc['id']} — {tc.get('title', '')}**  ·  covers {_join(tc.get('requirement_ids'))}")
            c1, c2, c3 = st.columns(3)
            c1.markdown("*Preconditions*\n" + "\n".join(f"- {p}" for p in tc.get("preconditions") or ["(none)"]))
            c2.markdown("*Steps*\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(tc.get("steps") or [], 1)))
            c3.markdown("*Expected*\n" + "\n".join(f"- {e}" for e in tc.get("expected_results") or []))
            if tc.get("test_data"):
                st.caption("Test data: " + _join(tc["test_data"]))
            st.divider()


def coverage_table(values: dict) -> tuple[pd.DataFrame, list[str]]:
    """Rows = requirements, columns = test case ids, '●' where covered."""
    coverage = values.get("coverage_matrix") or {}
    descriptions = {r["id"]: r.get("description", "") for r in (values.get("interpretation") or {}).get("requirements", [])}
    tc_ids = [tc["id"] for tc in values.get("test_cases", [])]
    by_req = coverage.get("by_requirement", {})
    rows = []
    for rid in by_req:
        row = {"requirement": rid, "description": descriptions.get(rid, "")[:70]}
        row.update({tc: "●" if tc in by_req[rid] else "" for tc in tc_ids})
        rows.append(row)
    table = pd.DataFrame(rows, columns=["requirement", "description", *tc_ids]).set_index("requirement")
    return table, list(coverage.get("uncovered", []))


def render_coverage(values: dict) -> None:
    coverage = values.get("coverage_matrix")
    if not coverage:
        if values.get("test_cases"):
            st.caption("Building coverage matrix…")
        return
    table, uncovered = coverage_table(values)

    def highlight(row: pd.Series) -> list[str]:
        style = "background-color: #ffd6d6; color: #8b0000; font-weight: 600" if row.name in uncovered else ""
        return [style] * len(row)

    st.markdown(f"**Coverage matrix** — {coverage.get('coverage_percent', 0)}% of requirements covered")
    st.dataframe(table.style.apply(highlight, axis=1))
    if uncovered:
        st.error("Uncovered requirements (highlighted): " + ", ".join(uncovered))
    if coverage.get("unknown_references"):
        st.warning(
            "Test cases referencing unknown requirement ids: "
            + "; ".join(f"{tc} → {_join(r)}" for tc, r in coverage["unknown_references"].items())
        )


def render_code(values: dict) -> None:
    site_context = values.get("site_context")
    if site_context is not None:
        if site_context.get("error"):
            st.warning(f"Could not capture the target page (code generated without a snapshot): {site_context['error'][:300]}")
        else:
            with st.expander(f"Page snapshot used for locators — {site_context.get('title', '')} ({site_context.get('url', '')})"):
                st.code(site_context.get("aria_snapshot", ""), language="yaml")
    code = values.get("generated_code")
    if not code:
        if values.get("test_cases_approved"):
            st.caption("Generating Playwright code…")
        return
    origin = {"generator": "Code Generator", "healer": "Healer", "human": "human edit"}.get(values.get("code_origin"), "")
    st.caption(f"Code version {values.get('code_version')} · from {origin}")
    for warning in values.get("code_warnings") or []:
        st.warning(warning)
    with st.expander("Generated test module (current version)", expanded=not values.get("execution_results")):
        st.code(code, language="python", line_numbers=True)


def _heal_records_after(values: dict, attempt_number: int) -> list[dict]:
    return [h for h in values.get("heal_history") or [] if h.get("after_attempt") == attempt_number]


def _render_attempt(attempt: dict, expanded: bool) -> None:
    summary = attempt.get("summary", {})
    icon = {"passed": "🟢", "failed": "🔴", "error": "💥"}.get(attempt["status"], "⚪")
    title = (
        f"{icon} Attempt {attempt['attempt']} · {attempt['label']} · {attempt['status'].upper()} "
        f"— passed {summary.get('passed', 0)}, failed {summary.get('failed', 0)}, errors {summary.get('error', 0)}"
    )
    with st.expander(title, expanded=expanded):
        rows = [
            {
                "": OUTCOME_ICON.get(t["outcome"], ""),
                "test": t["name"],
                "test case": t.get("test_case_id") or "",
                "outcome": t["outcome"],
                "classification": CATEGORY_LABELS.get(t.get("category", ""), ""),
                "reason": t.get("category_reason", ""),
                "seconds": round(t.get("duration", 0), 2),
            }
            for t in attempt["tests"]
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True)
        if attempt.get("missing_test_cases"):
            st.warning("Approved test cases with no test function: " + ", ".join(attempt["missing_test_cases"]))
        for t in attempt["tests"]:
            if t["outcome"] not in ("failed", "error"):
                continue
            st.markdown(f"**{t['name']}** — {t.get('message', '')[:300]}")
            st.code(t.get("details", ""), language="text")
            for shot in t.get("screenshots", [])[:2]:
                if Path(shot).exists():
                    st.image(shot, caption=Path(shot).name, width=480)
        st.markdown("**Logs**")
        st.code(attempt.get("logs", ""), language="text")
        st.caption(f"Artifacts: {attempt.get('artifacts_dir', '')}")


def _render_heal(heal: dict, code_before: str) -> None:
    ok = heal["status"] == "applied"
    title = f"{'🩹' if ok else '🚫'} Heal {heal['heal']} — {'applied' if ok else 'REJECTED by assertion guard'}"
    with st.expander(title, expanded=not ok):
        if heal.get("changes"):
            st.markdown(heal["changes"])
        for violation in heal.get("violations", []):
            st.error(violation)
        diff = "".join(
            difflib.unified_diff(
                code_before.splitlines(keepends=True),
                heal.get("candidate_code", "").splitlines(keepends=True),
                "before", "healer candidate",
            )
        )
        st.code(diff or "(no changes)", language="diff")


def render_self_repair(values: dict) -> None:
    attempts = values.get("execution_results") or []
    if not attempts:
        if values.get("code_run_confirmed"):
            st.caption("Running the generated tests…")
        return
    st.caption(f"1 original run + up to {MAX_HEAL_ATTEMPTS} heals. Heal attempts used: {values.get('heal_attempts', 0)}")
    for attempt in attempts:
        _render_attempt(attempt, expanded=attempt is attempts[-1])
        for heal in _heal_records_after(values, attempt["attempt"]):
            _render_heal(heal, attempt.get("code", ""))


def render_baseline(values: dict) -> None:
    if values.get("final_artifacts"):
        known = values.get("known_failures") or []
        st.success("Baseline approved and exported" + (f" with known failures: {', '.join(known)}" if known else ""))
        st.code(values["final_artifacts"]["dir"], language="text")
    elif values.get("baseline_approved"):
        st.caption("Exporting…")


def render_orchestrator_log(values: dict) -> None:
    history = values.get("history") or []
    if not history:
        st.caption("No routing decisions yet.")
        return
    rows = [{**h, "from": label(h.get("from")), "next": label(h.get("next"))} for h in history]
    st.dataframe(pd.DataFrame(rows, columns=["step", "time", "from", "next", "reason"]), hide_index=True)


def _render_test_cases_and_coverage(values: dict) -> None:
    render_test_cases(values)
    render_coverage(values)


RENDERERS = {
    "interpretation": render_interpretation,
    "scenarios": render_scenarios,
    "test_cases": _render_test_cases_and_coverage,
    "code": render_code,
    "self_repair": render_self_repair,
    "baseline": render_baseline,
}


def summarize_update(node: str, update: dict | None) -> str:
    """One-line description of a node's output for the live activity feed."""
    update = update or {}
    if update.get("halted_reason"):
        return f"halted: {update['halted_reason']}"
    if node == "interpreter" and update.get("interpretation"):
        i = update["interpretation"]
        return f"{len(i['requirements'])} requirements, {len(i['ambiguities'])} ambiguities"
    if node == "scenario_generator":
        return f"{len(update.get('scenarios', []))} scenarios"
    if node == "test_case_generator":
        return f"{len(update.get('test_cases', []))} test cases"
    if node == "coverage_builder":
        c = update.get("coverage_matrix") or {}
        return f"{c.get('coverage_percent', 0)}% coverage, uncovered: {', '.join(c.get('uncovered', [])) or 'none'}"
    if node == "site_explorer":
        sc = update.get("site_context") or {}
        return f"error: {sc['error'][:120]}" if sc.get("error") else f"captured '{sc.get('title', '')}'"
    if node == "code_generator":
        warnings = len(update.get("code_warnings") or [])
        return f"{len(update.get('generated_code', '').splitlines())} lines" + (f", {warnings} warnings" if warnings else "")
    if node == "executor":
        last = (update.get("execution_results") or [{}])[-1]
        s = last.get("summary", {})
        return f"{last.get('label')}: {str(last.get('status', '')).upper()} (passed {s.get('passed', 0)}, failed {s.get('failed', 0)}, errors {s.get('error', 0)})"
    if node == "healer":
        last = (update.get("heal_history") or [{}])[-1]
        return f"heal {last.get('heal')} {last.get('status')}"
    if node == "finalize":
        return (update.get("final_artifacts") or {}).get("dir", "")
    return "recorded decision"
