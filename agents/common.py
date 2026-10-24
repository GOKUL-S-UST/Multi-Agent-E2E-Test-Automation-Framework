"""Helpers shared by agents: context formatting, id handling and code extraction."""

from __future__ import annotations

import re
from typing import Any, Iterable

import yaml

_ID_NUM = re.compile(r"(\d+)\s*$")


def to_yaml(data: Any) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100).strip()


def target_fields(state: dict) -> dict[str, str]:
    site = state.get("target_site") or {}
    return {
        "target_name": site.get("name", "Unknown"),
        "target_url": site.get("url", ""),
        "target_description": site.get("description", ""),
        "credentials_available": "yes (TARGET_USERNAME / TARGET_PASSWORD)"
        if site.get("has_credentials")
        else "no",
    }


def interpretation_context(state: dict) -> str:
    """The approved interpretation plus the reviewer's answers to ambiguities."""
    interpretation = dict(state.get("interpretation") or {})
    answers = state.get("ambiguity_answers") or {}
    ambiguities = interpretation.pop("ambiguities", []) or []
    clarifications = []
    for amb in ambiguities:
        answer = (answers.get(amb.get("id", "")) or "").strip()
        clarifications.append(
            {
                "id": amb.get("id"),
                "question": amb.get("question"),
                "human_answer": answer or f"(no answer - use: {amb.get('suggested_resolution') or 'best judgement'})",
            }
        )
    if clarifications:
        interpretation["human_clarifications"] = clarifications
    return to_yaml(interpretation)


def feedback_block(state: dict, gate: str, label: str = "Reviewer feedback") -> str:
    entry = (state.get("gate_feedback") or {}).get(gate) or {}
    feedback = (entry.get("feedback") or "").strip()
    if not feedback:
        return ""
    parts = [f"\n{label} on the previous version (you MUST address it):\n{feedback}"]
    rejected = entry.get("rejected")
    if rejected:
        parts.append("\nPrevious (rejected) version for reference:\n" + to_yaml(rejected))
    return "\n".join(parts)


def format_id(prefix: str, number: int) -> str:
    return f"{prefix}-{number:03d}"


def max_id_number(ids: Iterable[str]) -> int:
    numbers = [int(m.group(1)) for i in ids if (m := _ID_NUM.search(str(i)))]
    return max(numbers, default=0)


def ensure_unique_ids(items: list[dict], prefix: str) -> list[dict]:
    """Keep LLM-provided ids when they are present and unique; otherwise assign new ones."""
    seen: set[str] = set()
    next_number = max_id_number(item.get("id", "") for item in items) + 1
    for item in items:
        item_id = str(item.get("id") or "").strip().upper()
        if not item_id or item_id in seen:
            item_id = format_id(prefix, next_number)
            next_number += 1
        item["id"] = item_id
        seen.add(item_id)
    return items


def test_function_name(test_case_id: str) -> str:
    slug = re.sub(r"[^0-9a-zA-Z]+", "_", test_case_id).strip("_").lower()
    return f"test_{slug}"


test_function_name.__test__ = False  # type: ignore[attr-defined]


def extract_python_block(text: str) -> str:
    blocks = re.findall(r"```(?:python|py)?[ \t]*\n(.*?)```", text, re.DOTALL)
    if blocks:
        return max(blocks, key=len).strip() + "\n"
    return text.strip() + "\n"


def text_after_code(text: str, marker: str = "CHANGES:") -> str:
    idx = text.rfind(marker)
    if idx == -1:
        return ""
    return text[idx + len(marker):].strip()


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated {len(text) - limit} characters]"
