"""Scenario Generator Agent: approved interpretation -> categorised scenarios."""

from __future__ import annotations

from agents.common import ensure_unique_ids, feedback_block, interpretation_context, target_fields
from llm import LLMClient
from prompts import load_prompt
from schemas import ScenarioSet


def run(state: dict, llm: LLMClient) -> dict:
    gate1 = (state.get("gate_feedback") or {}).get("gate1") or {}
    feedback = feedback_block(state, "gate1") if gate1.get("target") == "scenarios" else ""
    system, user = load_prompt("scenario_generator").render(
        interpretation=interpretation_context(state),
        feedback=feedback,
        **target_fields(state),
    )
    result = llm.generate_structured(ScenarioSet, system, user)
    scenarios = [s.model_dump() for s in result.scenarios]
    if not scenarios:
        raise ValueError("Scenario Generator returned no scenarios.")
    ensure_unique_ids(scenarios, "SC")
    return {"scenarios": scenarios}
