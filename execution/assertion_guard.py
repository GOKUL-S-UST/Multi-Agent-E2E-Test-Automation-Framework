"""Static checks that keep the healer from changing WHAT a test validates.

This is a lightweight, non-cryptographic stand-in for the production
"assertion hash lock". Signatures are deliberately normalised so that the
healer may still change *where* an assertion looks (the locator passed to
``expect(...)``) and *how long* it waits (``timeout=``), but not the matcher,
its expected values, or any plain ``assert`` statement.

The signature lists produced here are what a future hash lock would hash.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from dataclasses import dataclass, field

_IGNORED_KWARGS = {"timeout"}
_SKIP_CALLS = {"skip", "xfail", "skipif", "importorskip", "fail"}
MARKER_RE = re.compile(r"#\s*ASSERTIONS-(BEGIN|END)\s+([A-Za-z0-9_\-]+)")


@dataclass
class GuardResult:
    ok: bool
    violations: list[str] = field(default_factory=list)


def parse_errors(code: str) -> str | None:
    try:
        ast.parse(code)
    except SyntaxError as exc:
        return f"SyntaxError: {exc.msg} (line {exc.lineno})"
    return None


def _test_functions(tree: ast.AST) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    funcs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            funcs[node.name] = node
    return funcs


def test_function_names(code: str) -> list[str]:
    try:
        return list(_test_functions(ast.parse(code)))
    except SyntaxError:
        return []


test_function_names.__test__ = False  # type: ignore[attr-defined]


def _is_expect_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (isinstance(func, ast.Name) and func.id == "expect") or (
        isinstance(func, ast.Attribute) and func.attr == "expect"
    )


def _matcher_signature(call: ast.Call) -> str | None:
    """For ``expect(target).matcher(args)`` return ``expect(*).matcher(args)``."""
    func = call.func
    if not isinstance(func, ast.Attribute) or not _is_expect_call(func.value):
        return None
    args = [ast.unparse(a) for a in call.args]
    kwargs = [f"{k.arg}={ast.unparse(k.value)}" for k in call.keywords if k.arg not in _IGNORED_KWARGS]
    return f"expect(*).{func.attr}({', '.join(args + kwargs)})"


def _signatures_for(func: ast.AST) -> list[str]:
    signatures: list[str] = []
    for node in ast.walk(func):
        if isinstance(node, ast.Assert):
            signatures.append("assert " + ast.unparse(node.test))
        elif isinstance(node, ast.Call):
            sig = _matcher_signature(node)
            if sig:
                signatures.append(sig)
    return sorted(signatures)


def extract_assertion_signatures(code: str) -> dict[str, list[str]]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {}
    return {name: _signatures_for(func) for name, func in _test_functions(tree).items()}


def _skip_count(code: str) -> int:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return 0
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in _SKIP_CALLS:
            base = node.value
            # pytest.skip(...), pytest.mark.skip, pytest.mark.xfail, test.skip(...)
            if isinstance(base, ast.Name) and base.id in {"pytest", "test"}:
                count += 1
            elif isinstance(base, ast.Attribute) and base.attr == "mark":
                count += 1
    return count


def _markers(code: str) -> Counter:
    return Counter((m.group(1), m.group(2).upper()) for m in MARKER_RE.finditer(code))


def marker_test_case_ids(code: str) -> set[str]:
    return {tc for kind, tc in _markers(code) if kind == "BEGIN"}


def function_fingerprints(code: str) -> dict[str, str]:
    """Formatting/comment-insensitive fingerprint of each test function."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {}
    return {name: ast.dump(func, annotate_fields=False) for name, func in _test_functions(tree).items()}


def check_heal(
    original_code: str,
    candidate_code: str,
    assertion_baseline: dict[str, list[str]],
    passed_tests: list[str] | None = None,
) -> GuardResult:
    """Validate a healed module against the governance rules."""
    violations: list[str] = []

    error = parse_errors(candidate_code)
    if error:
        return GuardResult(False, [f"Healed code does not parse: {error}"])

    baseline = assertion_baseline or extract_assertion_signatures(original_code)
    candidate = extract_assertion_signatures(candidate_code)

    missing = sorted(set(baseline) - set(candidate))
    added = sorted(set(candidate) - set(baseline))
    if missing:
        violations.append(f"Test functions removed or renamed: {', '.join(missing)}")
    if added:
        violations.append(f"Test functions added: {', '.join(added)}")

    for name in sorted(set(baseline) & set(candidate)):
        before, after = Counter(baseline[name]), Counter(candidate[name])
        if before != after:
            removed = list((before - after).elements())
            introduced = list((after - before).elements())
            detail = []
            if removed:
                detail.append("removed/changed: " + "; ".join(removed))
            if introduced:
                detail.append("introduced: " + "; ".join(introduced))
            violations.append(f"Assertions changed in {name} ({' | '.join(detail)})")

    if _skip_count(candidate_code) > _skip_count(original_code):
        violations.append("Skip/xfail/fail markers or calls were added")

    original_markers = _markers(original_code)
    candidate_markers = _markers(candidate_code)
    lost = original_markers - candidate_markers
    if lost:
        violations.append(
            "Assertion block markers removed: " + ", ".join(f"{k} {tc}" for (k, tc) in sorted(lost.elements()))
        )

    if passed_tests:
        before_fp = function_fingerprints(original_code)
        after_fp = function_fingerprints(candidate_code)
        changed = [t for t in passed_tests if t in before_fp and before_fp.get(t) != after_fp.get(t)]
        if changed:
            violations.append(f"Passing tests were modified: {', '.join(sorted(changed))}")

    return GuardResult(not violations, violations)
