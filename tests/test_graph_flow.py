"""End-to-end graph behaviour with a fake LLM and a stubbed executor."""

import pytest
from langgraph.types import Command

from graph import RECURSION_LIMIT, build_graph, initial_state
from tests.fakes import CHEATING_CODE, HEALED_CODE, FakeLLM

SITE = {"key": "custom", "name": "Demo", "url": "https://example.com", "has_credentials": False}


def _result(status, healable=True, category="mechanical"):
    tests = [
        {"name": "test_tc_001", "test_case_id": "TC-001", "outcome": "passed"},
        {
            "name": "test_tc_002",
            "test_case_id": "TC-002",
            "outcome": "passed" if status == "passed" else "failed",
            "message": "boom",
            "category": category,
        },
    ]
    return {"status": status, "summary": {}, "tests": tests, "healable": healable, "logs": "", "artifacts_dir": ""}


@pytest.fixture
def harness(monkeypatch, tmp_path):
    def make(fake: FakeLLM, run_results: list[dict], **configurable):
        executed_code = []

        def fake_run_suite(code, **kwargs):
            executed_code.append(code)
            return run_results.pop(0)

        monkeypatch.setattr("execution.runner.run_suite", fake_run_suite)
        monkeypatch.setattr("execution.site_explorer.explore", lambda url: {"url": url, "title": "Demo", "aria_snapshot": "- button"})
        monkeypatch.setattr("graph.nodes.OUTPUT_DIR", tmp_path)
        graph = build_graph(llm_factory=lambda cfg: fake)
        config = {"configurable": {"thread_id": "t1", **configurable}, "recursion_limit": RECURSION_LIMIT}

        def step(inp):
            for _ in graph.stream(inp, config, stream_mode="updates"):
                pass
            snap = graph.get_state(config)
            pending = [i.value["gate"] for t in snap.tasks for i in t.interrupts]
            return snap.values, (pending[0] if pending else None)

        return step, executed_code

    return make


def start():
    return initial_state("Users log in with username and password.", "text", SITE)


def test_happy_path_with_heal(harness):
    fake = FakeLLM()
    step, executed = harness(fake, [_result("failed"), _result("passed")])

    values, gate = step(start())
    assert gate == "gate0" and values["interpretation"]["requirements"]

    values, gate = step(Command(resume={"action": "approve", "ambiguity_answers": {"AMB-001": "Show 'Bad credentials'"}}))
    assert gate == "gate1"
    assert values["coverage_matrix"]["uncovered"] == ["REQ-003"]
    # The answer to the ambiguity is passed to downstream agents.
    assert "Show 'Bad credentials'" in [u for name, u in fake.calls if name == "ScenarioSet"][0]

    values, gate = step(Command(resume={"action": "fill_gaps"}))
    assert gate == "gate1"
    assert [tc["id"] for tc in values["test_cases"]] == ["TC-001", "TC-002", "TC-003"]
    assert values["coverage_matrix"]["uncovered"] == []

    values, gate = step(Command(resume={"action": "approve"}))
    assert gate == "confirm_run"
    assert values["site_context"]["title"] == "Demo"
    assert values["code_warnings"]  # TC-003 has no function in the fake code

    values, gate = step(Command(resume={"action": "run"}))
    assert gate == "gate2"
    assert [a["status"] for a in values["execution_results"]] == ["failed", "passed"]
    assert [a["label"] for a in values["execution_results"]] == ["Original", "Heal 1"]
    assert executed[1] == HEALED_CODE
    assert values["heal_history"][0]["status"] == "applied"

    values, gate = step(Command(resume={"action": "approve"}))
    assert gate is None
    assert values["final_artifacts"]["files"]["test_generated.py"].endswith("test_generated.py")
    nexts = [h["next"] for h in values["history"]]
    assert nexts[-2:] == ["finalize", "END"]
    assert "healer" in nexts


def test_heal_that_changes_assertions_is_rejected_and_loop_stops_after_two(harness):
    cheat = f"```python\n{CHEATING_CODE}```"
    fake = FakeLLM(heal_responses=[cheat, cheat])
    step, executed = harness(fake, [_result("failed")])

    step(start())
    step(Command(resume={"action": "approve"}))
    step(Command(resume={"action": "approve"}))
    values, gate = step(Command(resume={"action": "run"}))
    assert gate == "gate2"
    assert len(executed) == 1  # rejected heals are never executed
    assert [h["status"] for h in values["heal_history"]] == ["rejected", "rejected"]
    assert values["heal_attempts"] == 2
    assert "CHEAT" not in values["generated_code"]
    assert values["generated_code"] != CHEATING_CODE


def test_max_three_runs(harness):
    fake = FakeLLM(heal_responses=[f"```python\n{HEALED_CODE}```", f"```python\n{HEALED_CODE.replace('get_by_test_id("error")', 'locator("#error")')}```"])
    step, executed = harness(fake, [_result("failed"), _result("failed"), _result("failed")])
    step(start())
    step(Command(resume={"action": "approve"}))
    step(Command(resume={"action": "approve"}))
    values, gate = step(Command(resume={"action": "run"}))
    assert gate == "gate2"
    assert len(values["execution_results"]) == 3
    assert [h["status"] for h in values["heal_history"]] == ["applied", "applied"]
    assert values["heal_attempts"] == 2


def test_real_failure_is_not_healed(harness):
    fake = FakeLLM()
    step, executed = harness(fake, [_result("failed", healable=False, category="assertion")])
    step(start())
    step(Command(resume={"action": "approve"}))
    step(Command(resume={"action": "approve"}))
    values, gate = step(Command(resume={"action": "run"}))
    assert gate == "gate2" and values["heal_attempts"] == 0

    values, gate = step(Command(resume={"action": "approve"}))
    assert values["known_failures"] == ["TC-002"]


def test_gate_rejections_regenerate_then_halt(harness):
    fake = FakeLLM()
    step, _ = harness(fake, [])
    step(start())
    for _ in range(2):
        values, gate = step(Command(resume={"action": "reject", "feedback": "Split REQ-001"}))
        assert gate == "gate0"
    assert "Split REQ-001" in [u for name, u in fake.calls if name == "Interpretation"][-1]
    values, gate = step(Command(resume={"action": "reject", "feedback": "Still wrong"}))
    assert gate is None and "GATE0" in values["halted_reason"]


def test_gate1_reject_to_scenarios_and_gate2_back_to_gate1(harness):
    fake = FakeLLM()
    step, _ = harness(fake, [_result("passed")])
    step(start())
    step(Command(resume={"action": "approve"}))
    values, gate = step(Command(resume={"action": "reject", "feedback": "More security", "target": "scenarios"}))
    assert gate == "gate1"
    assert sum(1 for name, _ in fake.calls if name == "ScenarioSet") == 2

    step(Command(resume={"action": "approve"}))
    values, gate = step(Command(resume={"action": "run"}))
    assert gate == "gate2"
    values, gate = step(Command(resume={"action": "reject", "feedback": "Use test ids", "target": "gate1"}))
    assert gate == "gate1" and values["generated_code"] == ""
    step(Command(resume={"action": "approve"}))
    assert "Use test ids" in [u for name, u in fake.calls if name == "code"][-1]


def test_gate1_edit_rebuilds_coverage(harness):
    fake = FakeLLM()
    step, _ = harness(fake, [_result("passed")])
    step(start())
    values, _ = step(Command(resume={"action": "approve"}))
    edited = values["test_cases"] + [{"id": "TC-009", "title": "Locked", "requirement_ids": ["REQ-003"]}]
    values, gate = step(Command(resume={"action": "edit", "test_cases": edited}))
    assert gate == "gate1" and values["coverage_matrix"]["uncovered"] == []


def test_gate2_human_edit_reruns(harness):
    fake = FakeLLM()
    step, executed = harness(fake, [_result("failed", healable=False, category="assertion"), _result("passed")])
    step(start())
    step(Command(resume={"action": "approve"}))
    step(Command(resume={"action": "approve"}))
    step(Command(resume={"action": "run"}))
    values, gate = step(Command(resume={"action": "edit", "code": CHEATING_CODE}))
    assert gate == "gate2"
    assert executed[-1] == CHEATING_CODE
    assert values["execution_results"][-1]["label"] == "Human edit"


def test_auto_run_skips_run_confirmation(harness):
    step, executed = harness(FakeLLM(), [_result("passed")], auto_run=True)
    _, gate = step(start())
    _, gate = step(Command(resume={"action": "approve"}))
    values, gate = step(Command(resume={"action": "approve"}))
    assert gate == "gate2"
    assert len(executed) == 1
    assert values["code_run_confirmed"]
