"""Graph node wrappers around agents and execution helpers."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from langchain_core.runnables import RunnableConfig

from agents import code_generator, coverage_builder, healer, interpreter, scenario_generator, test_case_generator
from config import OUTPUT_DIR, execution_timeout_seconds
from execution import runner, site_explorer
from llm import LLMClient

LLMFactory = Callable[[RunnableConfig], LLMClient]


def _configurable(config: RunnableConfig | None) -> dict[str, Any]:
    return dict((config or {}).get("configurable") or {})


def _thread_dir(config: RunnableConfig | None) -> str:
    thread = str(_configurable(config).get("thread_id", "default"))
    return re.sub(r"[^A-Za-z0-9_-]", "_", thread)[:40] or "default"


def make_agent_nodes(llm_factory: LLMFactory) -> dict[str, Callable]:
    def interpreter_node(state: dict, config: RunnableConfig) -> dict:
        return interpreter.run(state, llm_factory(config))

    def scenario_node(state: dict, config: RunnableConfig) -> dict:
        return scenario_generator.run(state, llm_factory(config))

    def test_case_node(state: dict, config: RunnableConfig) -> dict:
        return test_case_generator.run(state, llm_factory(config))

    def code_generator_node(state: dict, config: RunnableConfig) -> dict:
        return code_generator.run(state, llm_factory(config))

    def healer_node(state: dict, config: RunnableConfig) -> dict:
        return healer.run(state, llm_factory(config))

    return {
        "interpreter": interpreter_node,
        "scenario_generator": scenario_node,
        "test_case_generator": test_case_node,
        "code_generator": code_generator_node,
        "healer": healer_node,
    }


def coverage_node(state: dict) -> dict:
    return coverage_builder.run(state)


def site_explorer_node(state: dict) -> dict:
    url = (state.get("target_site") or {}).get("url", "")
    return {"site_context": site_explorer.explore(url)}


def executor_node(state: dict, config: RunnableConfig) -> dict:
    attempts = list(state.get("execution_results") or [])
    number = len(attempts) + 1
    heals = int(state.get("heal_attempts", 0))
    origin = state.get("code_origin")
    if number == 1:
        label = "Original"
    elif origin == "healer":
        label = f"Heal {heals}"
    elif origin == "human":
        label = "Human edit"
    else:
        label = f"Run {number}"

    site = state.get("target_site") or {}
    opts = _configurable(config)
    run_dir = OUTPUT_DIR / "runs" / _thread_dir(config) / f"attempt-{number}-v{state.get('code_version', 0)}"
    result = runner.run_suite(
        state.get("generated_code", ""),
        base_url=site.get("url", ""),
        run_dir=run_dir,
        test_case_ids=[tc["id"] for tc in state.get("test_cases", [])],
        credentials=runner.resolve_credentials(site),
        headed=bool(opts.get("headed", False)),
        browser=str(opts.get("browser", "chromium")),
        timeout_seconds=int(opts.get("timeout_seconds") or execution_timeout_seconds()),
    )
    attempts.append(
        {
            "attempt": number,
            "label": label,
            "code_version": state.get("code_version"),
            "code": state.get("generated_code", ""),
            "finished_at": datetime.now().strftime("%H:%M:%S"),
            **result,
        }
    )
    return {"execution_results": attempts}


def _write(path: Path, content: str) -> str:
    path.write_text(content, encoding="utf-8")
    return str(path)


def finalize_node(state: dict, config: RunnableConfig) -> dict:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = OUTPUT_DIR / "suites" / f"{stamp}-{_thread_dir(config)[:8]}"
    out_dir.mkdir(parents=True, exist_ok=True)
    attempts = state.get("execution_results") or []
    site = state.get("target_site") or {}

    manifest = {
        "created_at": stamp,
        "target_site": {k: site.get(k) for k in ("key", "name", "url")},
        "requirement_source": state.get("requirement_source"),
        "raw_requirement": state.get("raw_requirement"),
        "interpretation": state.get("interpretation"),
        "ambiguity_answers": state.get("ambiguity_answers"),
        "scenarios": state.get("scenarios"),
        "test_cases": state.get("test_cases"),
        "coverage_matrix": state.get("coverage_matrix"),
        "known_failures": state.get("known_failures"),
        # Input for the future assertion hash lock.
        "assertion_signatures": state.get("assertion_baseline"),
        "execution_attempts": [
            {k: a.get(k) for k in ("attempt", "label", "status", "summary", "code_version")} for a in attempts
        ],
        "heal_history": [{k: v for k, v in h.items() if k != "candidate_code"} for h in state.get("heal_history", [])],
        "orchestrator_history": state.get("history"),
    }
    readme = (
        "Approved Phase 1 baseline\n"
        "=========================\n\n"
        f"Target: {site.get('url')}\n\n"
        "Run it:\n"
        f"    pytest test_generated.py --base-url {site.get('url')}\n\n"
        "Credentials (if needed) are read from TARGET_USERNAME / TARGET_PASSWORD.\n"
    )
    files = {
        "test_generated.py": _write(out_dir / "test_generated.py", state.get("generated_code", "")),
        "manifest.json": _write(out_dir / "manifest.json", json.dumps(manifest, indent=2, default=str)),
        "README.txt": _write(out_dir / "README.txt", readme),
    }
    return {"final_artifacts": {"dir": str(out_dir), "files": files}}
