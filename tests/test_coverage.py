from agents.coverage_builder import build_coverage


def test_coverage_matrix_flags_uncovered_and_unknown():
    reqs = [{"id": "REQ-001"}, {"id": "REQ-002"}, {"id": "REQ-003"}]
    cases = [
        {"id": "TC-001", "requirement_ids": ["REQ-001", "REQ-002"]},
        {"id": "TC-002", "requirement_ids": ["REQ-001", "REQ-999"]},
    ]
    cov = build_coverage(reqs, cases)
    assert cov["by_requirement"] == {"REQ-001": ["TC-001", "TC-002"], "REQ-002": ["TC-001"], "REQ-003": []}
    assert cov["uncovered"] == ["REQ-003"]
    assert cov["unknown_references"] == {"TC-002": ["REQ-999"]}
    assert cov["coverage_percent"] == 66.7


def test_coverage_with_no_requirements():
    assert build_coverage([], [])["coverage_percent"] == 0.0
