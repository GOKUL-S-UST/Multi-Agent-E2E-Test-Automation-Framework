import pytest
from langgraph.graph import END

from graph import initial_state
from graph.orchestrator import decide_next, orchestrator_node, route


def base(**overrides):
    state = initial_state("Users can log in", "text", {"url": "https://example.com"})
    state.update(overrides)
    return state


APPROVED_TESTS = dict(
    interpretation={"requirements": [{"id": "REQ-001"}]},
    interpretation_approved=True,
    scenarios=[{"id": "SC-001"}],
    test_cases=[{"id": "TC-001", "requirement_ids": ["REQ-001"]}],
    coverage_matrix={"by_requirement": {}, "uncovered": []},
    test_cases_approved=True,
    site_context={"url": "x"},
)


def attempt(status, version=1, healable=True):
    return {"attempt": 1, "status": status, "code_version": version, "healable": healable, "tests": []}


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({}, "interpreter"),
        ({"raw_requirement": "  "}, END),
        ({"interpretation": {"requirements": []}}, "gate0"),
        ({"interpretation": {"x": 1}, "interpretation_approved": True}, "scenario_generator"),
        ({"interpretation": {"x": 1}, "interpretation_approved": True, "scenarios": [{}]}, "test_case_generator"),
        ({**APPROVED_TESTS, "coverage_matrix": None, "test_cases_approved": False}, "coverage_builder"),
        ({**APPROVED_TESTS, "test_cases_approved": False}, "gate1"),
        ({**APPROVED_TESTS, "test_cases_approved": False, "gap_fill_requested": True}, "test_case_generator"),
        ({**APPROVED_TESTS, "site_context": None}, "site_explorer"),
        ({**APPROVED_TESTS}, "code_generator"),
        ({**APPROVED_TESTS, "generated_code": "x", "code_version": 1}, "confirm_run"),
        ({**APPROVED_TESTS, "generated_code": "x", "code_version": 1, "code_run_confirmed": True}, "executor"),
        ({**APPROVED_TESTS, "generated_code": "x", "code_version": 1, "execution_results": [attempt("passed")]}, "gate2"),
        ({**APPROVED_TESTS, "generated_code": "x", "code_version": 1, "execution_results": [attempt("failed")]}, "healer"),
        (
            {**APPROVED_TESTS, "generated_code": "x", "code_version": 1,
             "execution_results": [attempt("failed", healable=False)]},
            "gate2",
        ),
        (
            {**APPROVED_TESTS, "generated_code": "x", "code_version": 1, "heal_attempts": 2,
             "execution_results": [attempt("failed")]},
            "gate2",
        ),
        (
            {**APPROVED_TESTS, "generated_code": "x", "code_version": 2, "heal_attempts": 1,
             "code_run_confirmed": True, "execution_results": [attempt("failed")]},
            "executor",
        ),
        (
            {**APPROVED_TESTS, "generated_code": "x", "code_version": 1, "baseline_approved": True,
             "execution_results": [attempt("passed")]},
            "finalize",
        ),
        ({"final_artifacts": {"dir": "x"}}, END),
        ({"halted_reason": "stop"}, END),
    ],
)
def test_decide_next(overrides, expected):
    assert decide_next(base(**overrides))[0] == expected


def test_orchestrator_node_records_history_and_route_follows_it():
    state = base()
    update = orchestrator_node(state)
    assert update["next_node"] == "interpreter"
    assert update["history"][-1]["next"] == "interpreter"
    assert update["history"][-1]["reason"]
    assert route({**state, **update}) == "interpreter"
