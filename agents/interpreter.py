"""Interpreter Agent: raw requirement -> structured interpretation."""

from __future__ import annotations

from agents.common import ensure_unique_ids, feedback_block, target_fields
from llm import LLMClient
from prompts import load_prompt
from schemas import Interpretation


def run(state: dict, llm: LLMClient) -> dict:
    system, user = load_prompt("interpreter").render(
        raw_requirement=state.get("raw_requirement", ""),
        requirement_source=state.get("requirement_source", "text"),
        feedback=feedback_block(state, "gate0"),
        **target_fields(state),
    )
    result = llm.generate_structured(Interpretation, system, user)
    data = result.model_dump()
    if not data["requirements"]:
        raise ValueError("Interpreter returned no requirements; retry or refine the requirement text.")
    ensure_unique_ids(data["requirements"], "REQ")
    ensure_unique_ids(data["rules"], "BR")
    ensure_unique_ids(data["assumptions"], "A")
    ensure_unique_ids(data["ambiguities"], "AMB")
    return {"interpretation": data, "interpretation_approved": False}
