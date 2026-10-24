"""Pydantic models for structured LLM output and human edits.

The schemas intentionally avoid free-form ``dict`` fields because several
providers (including Gemini structured output) handle them poorly. Test data
is therefore modelled as a list of name/value pairs and converted to a dict
when stored in the graph state.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Priority = Literal["high", "medium", "low"]
ScenarioCategory = Literal["functional", "negative", "boundary", "integration", "security"]


class Requirement(BaseModel):
    id: str = Field(description="Stable identifier, e.g. REQ-001")
    description: str = Field(description="A single, testable requirement statement")
    priority: Priority = "medium"
    source_excerpt: str = Field(default="", description="Verbatim text from the source requirement")


class Rule(BaseModel):
    id: str = Field(description="Identifier, e.g. BR-001")
    description: str
    requirement_ids: list[str] = Field(default_factory=list)


class Entity(BaseModel):
    name: str
    description: str = ""
    attributes: list[str] = Field(default_factory=list)


class Assumption(BaseModel):
    id: str = Field(description="Identifier, e.g. A-001")
    description: str


class Ambiguity(BaseModel):
    id: str = Field(description="Identifier, e.g. AMB-001")
    question: str = Field(description="Question a human must answer to remove the ambiguity")
    impact: str = Field(default="", description="What goes wrong in testing if this is guessed wrong")
    suggested_resolution: str = ""


class Interpretation(BaseModel):
    summary: str = ""
    requirements: list[Requirement] = Field(default_factory=list)
    rules: list[Rule] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    ambiguities: list[Ambiguity] = Field(default_factory=list)


class Scenario(BaseModel):
    id: str = Field(description="Identifier, e.g. SC-001")
    title: str
    category: ScenarioCategory
    description: str = ""
    requirement_ids: list[str] = Field(default_factory=list)
    priority: Priority = "medium"


class ScenarioSet(BaseModel):
    scenarios: list[Scenario]


class TestDataItem(BaseModel):
    name: str
    value: str


class TestCase(BaseModel):
    __test__ = False  # stop pytest from collecting this model

    id: str = Field(description="Identifier, e.g. TC-001")
    title: str
    scenario_id: str = ""
    requirement_ids: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    expected_results: list[str] = Field(default_factory=list)
    test_data: list[TestDataItem] = Field(default_factory=list)
    priority: Priority = "medium"


class TestCaseSet(BaseModel):
    __test__ = False

    test_cases: list[TestCase]


def test_case_to_state(tc: TestCase) -> dict:
    data = tc.model_dump()
    data["test_data"] = {item.name: item.value for item in tc.test_data}
    return data


def test_case_from_state(data: dict) -> TestCase:
    payload = dict(data)
    test_data = payload.get("test_data") or {}
    if isinstance(test_data, dict):
        payload["test_data"] = [{"name": str(k), "value": str(v)} for k, v in test_data.items()]
    return TestCase.model_validate(payload)


test_case_to_state.__test__ = False  # type: ignore[attr-defined]
test_case_from_state.__test__ = False  # type: ignore[attr-defined]
