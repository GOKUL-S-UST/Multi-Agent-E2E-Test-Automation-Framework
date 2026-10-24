from execution.assertion_guard import check_heal, extract_assertion_signatures, marker_test_case_ids
from tests.fakes import CHEATING_CODE, GOOD_CODE, HEALED_CODE


def test_signatures_ignore_locator_and_timeout():
    sigs = extract_assertion_signatures(GOOD_CODE)
    assert sigs["test_tc_002"] == ["expect(*).to_have_text('Bad credentials')"]
    changed = GOOD_CODE.replace('to_have_text("Bad credentials")', 'to_have_text("Bad credentials", timeout=10000)')
    assert extract_assertion_signatures(changed) == sigs


def test_locator_heal_is_allowed():
    baseline = extract_assertion_signatures(GOOD_CODE)
    result = check_heal(GOOD_CODE, HEALED_CODE, baseline, passed_tests=["test_tc_001"])
    assert result.ok, result.violations


def test_changed_matcher_is_rejected():
    baseline = extract_assertion_signatures(GOOD_CODE)
    result = check_heal(GOOD_CODE, CHEATING_CODE, baseline)
    assert not result.ok
    assert "Assertions changed in test_tc_002" in result.violations[0]


def test_removed_test_skip_markers_and_passing_edits_rejected():
    baseline = extract_assertion_signatures(GOOD_CODE)
    removed = GOOD_CODE.split("def test_tc_002")[0]
    assert any("removed" in v for v in check_heal(GOOD_CODE, removed, baseline).violations)

    skipped = GOOD_CODE.replace("def test_tc_002", "import pytest\n\n@pytest.mark.skip\ndef test_tc_002")
    assert any("Skip" in v for v in check_heal(GOOD_CODE, skipped, baseline).violations)

    no_markers = GOOD_CODE.replace("# ASSERTIONS-END TC-002", "")
    assert any("markers" in v for v in check_heal(GOOD_CODE, no_markers, baseline).violations)

    touched_passing = GOOD_CODE.replace('name="Login").click()', 'name="Sign in").click()', 1)
    result = check_heal(GOOD_CODE, touched_passing, baseline, passed_tests=["test_tc_001"])
    assert any("Passing tests were modified" in v for v in result.violations)


def test_plain_assert_changes_rejected_and_syntax_errors_caught():
    code = "def test_a(page):\n    assert page.title() == 'Home'\n"
    baseline = extract_assertion_signatures(code)
    assert not check_heal(code, code.replace("'Home'", "'Other'"), baseline).ok
    assert not check_heal(code, "def test_a(:\n", baseline).ok


def test_marker_ids():
    assert marker_test_case_ids(GOOD_CODE) == {"TC-001", "TC-002"}
