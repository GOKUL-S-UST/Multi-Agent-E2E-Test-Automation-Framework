"""Coverage Matrix Builder: purely mechanical, no LLM.

Each test case declares the requirement ids it covers; the matrix is the
inverse index of that declaration.
"""

from __future__ import annotations


def build_coverage(requirements: list[dict], test_cases: list[dict]) -> dict:
    requirement_ids = [r["id"] for r in requirements]
    known = set(requirement_ids)
    by_requirement: dict[str, list[str]] = {rid: [] for rid in requirement_ids}
    unknown_references: dict[str, list[str]] = {}

    for tc in test_cases:
        for rid in tc.get("requirement_ids") or []:
            if rid in known:
                if tc["id"] not in by_requirement[rid]:
                    by_requirement[rid].append(tc["id"])
            else:
                unknown_references.setdefault(tc["id"], []).append(rid)

    uncovered = [rid for rid in requirement_ids if not by_requirement[rid]]
    covered = len(requirement_ids) - len(uncovered)
    return {
        "by_requirement": by_requirement,
        "uncovered": uncovered,
        "unknown_references": unknown_references,
        "coverage_percent": round(100 * covered / len(requirement_ids), 1) if requirement_ids else 0.0,
    }


def run(state: dict) -> dict:
    requirements = (state.get("interpretation") or {}).get("requirements", [])
    return {"coverage_matrix": build_coverage(requirements, state.get("test_cases", []))}
