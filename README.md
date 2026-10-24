# Multi-Agent E2E Test Automation Framework — Phase 1 POC

A Streamlit + LangGraph proof of concept for **Phase 1 (Cold Start)** of an
AI-native end-to-end test suite. One business requirement goes in; an
approved, executable Playwright (Python) test suite comes out. Humans take
part at three approval gates and do not write the tests.

> **Governance principle:** the AI may change *how* a test navigates a page,
> never *what* it validates. This POC enforces that with an AST-based assertion
> guard (see [Governance](#governance-assertion-guard)). The production hash
> lock is out of scope, but the design leaves room for it.

---

## Quick start (Windows + uv)

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```powershell
uv venv --python 3.11
.venv\Scripts\activate
uv pip install -r requirements.txt
python -m playwright install chromium
copy .env.example .env      # then set GOOGLE_API_KEY (and site credentials if needed)
streamlit run app.py
```

On macOS/Linux, activate with `source .venv/bin/activate` and use `cp` instead of `copy`.

### Configuration (`.env`)

| Variable | Purpose |
|---|---|
| `LLM_PROVIDER` | `gemini` (default), `openai`, `anthropic`, `ollama` |
| `LLM_MODEL` | Default `gemini-3.8-flash`; can also be changed in the sidebar |
| `GOOGLE_API_KEY` | Gemini key (`GEMINI_API_KEY` also works) |
| `SAUCEDEMO_USERNAME` / `SAUCEDEMO_PASSWORD` | Credentials for the SauceDemo preset |
| `CUSTOM_SITE_USERNAME` / `CUSTOM_SITE_PASSWORD` | Credentials for a custom URL |
| `EXECUTION_TIMEOUT_SECONDS` | Timeout for each test run |

Other providers need their LangChain package. The lines are commented out in
`requirements.txt`; uncomment the one you need.

Credentials are never sent to the LLM. Generated tests read them from the
`TARGET_USERNAME` / `TARGET_PASSWORD` environment variables, which the runner
sets from the selected site's variables.

---

## Using the app

1. **Sidebar:** pick a target site, either a preset (SauceDemo, The Internet,
   DemoQA) or **Custom URL…** for your own app. Then choose the LLM
   provider/model and the execution options (auto-run, headed browser, timeout).
   **Reset session** starts over.
2. Paste a requirement or upload a `.txt` / `.md` file, then click **Start Phase 1**.
3. Each stage appears in the vertical flow as soon as the graph produces it.
   - **Gate 0:** review the interpretation. Answer ambiguities, edit the YAML,
     or reject with feedback.
   - **Gate 1:** review the test cases and the coverage matrix (uncovered
     requirements are shown in red). You can edit cases as a table or as YAML,
     **Generate for uncovered**, or reject back to test cases or scenarios.
   - **Run confirmation:** review the generated code before it first runs.
     Turn on *Auto-run* to skip this step.
   - **Self-repair loop:** shows every attempt (Original, Heal 1, Heal 2) with
     pass/fail, per-test results, logs and heal diffs.
   - **Gate 2:** approve the baseline, approve it with the remaining failures
     recorded as known failures, edit the code (this re-runs it), or reject.
4. The approved suite is exported to `output/suites/<timestamp>-<id>/`
   (`test_generated.py`, `manifest.json`, `README.txt`). You can also download
   these files from the UI.
5. The **Orchestrator log** lists every routing decision in order.

---

## Architecture

```
app.py (Streamlit)  ──stream(updates)──►  LangGraph (MemorySaver checkpointer)
                                           │
              ┌────────────────────────────┴───────────────────────────┐
              │                     orchestrator                        │
              │  (node logs decision → conditional edge routes on state) │
              └──┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬────┘
                 ▼      ▼      ▼      ▼      ▼      ▼      ▼      ▼
         interpreter gate0 scenario test_case coverage gate1 site_explorer code_generator
         confirm_run executor healer gate2 finalize            (every node returns to orchestrator)
```

Every agent and gate node goes back to the `orchestrator` node. The
orchestrator appends a decision to `history`, and a **deterministic**
conditional edge (`graph/orchestrator.py::decide_next`, no LLM call) picks the
next node based on what is populated and what is approved:

| # | Condition | Next |
|---|---|---|
| 1 | halted / exported / empty requirement | END |
| 2 | no interpretation | interpreter |
| 3 | interpretation not approved | gate0 |
| 4 | no scenarios | scenario_generator |
| 5 | no test cases, or gap fill requested | test_case_generator |
| 6 | no coverage matrix | coverage_builder |
| 7 | test cases not approved | gate1 |
| 8 | no site snapshot | site_explorer |
| 9 | no code | code_generator |
| 10 | baseline approved | finalize |
| 11 | current code version not yet run | confirm_run → executor |
| 12 | passed, or 2 heals used, or failure not healable | gate2 |
| 13 | otherwise | healer |

Gates are LangGraph `interrupt()`s. The UI resumes them with
`Command(resume={...})`. When a gate rejects, it clears the artifacts
downstream of it, so routing stays a pure function of state. A third rejection
at the same gate halts the run.

### Self-repair loop

There are at most **3 runs**: the original plus 2 heals. Each run happens in a
`pytest` subprocess with its own run directory under `output/runs/`. Failures
are classified as:

- **mechanical:** locator, timeout or navigation problems
- **code_error:** syntax, name or attribute errors
- **assertion:** an `expect`/`assert` mismatch
- **server:** 5xx responses
- **environment:** browser missing, connection refused

Only mechanical, code_error and unknown failures go to the **Healer**.
Assertion and server failures go straight to Gate 2 as real failures, with
evidence attached: screenshot, page ARIA snapshot and logs.

### Governance (assertion guard)

Generated code marks every test's validation block with
`# ASSERTIONS-BEGIN TC-xxx` / `# ASSERTIONS-END TC-xxx`.
`execution/assertion_guard.py` rejects any heal that:

- changes assertions (matcher, expected values, plain `assert` statements);
- adds or removes tests;
- adds skip/xfail markers;
- drops the markers;
- modifies tests that were passing.

Rejected heals are recorded in the UI and never executed. To add a hash lock
later, hash the signatures this module already extracts.

### State

`graph/state.py::PipelineState` holds the fields from the brief:

- `raw_requirement`, `interpretation`, `interpretation_approved`
- `scenarios`, `test_cases`, `coverage_matrix`, `test_cases_approved`
- `generated_code`, `execution_results`, `baseline_approved`
- `current_stage`, `history`

It also holds supporting fields such as `gate_feedback`, `site_context`,
`heal_history`, `known_failures` and `final_artifacts`.

---

## Project layout

```
app.py              Streamlit UI (sidebar, live stage rendering, gate cards)
ui/                 Renderers and gate cards
graph/              State, orchestrator (routing), gates, nodes, graph builder
agents/             One pure function of state per agent
                    (interpreter, scenario_generator, test_case_generator,
                     coverage_builder, code_generator, healer)
prompts/            One prompt template per LLM agent (=== SYSTEM === / === USER ===)
execution/          Playwright runner, site explorer, failure classifier, assertion guard
llm/                Provider-agnostic LLM wrapper (LLM_PROVIDER / LLM_MODEL)
schemas/            Pydantic models for structured LLM output
config/             Settings and target-site presets
tests/              Unit and flow tests (fake LLM) plus a real-Playwright runner test
```

## Running the tests

```powershell
python -m pytest -q
```

The flow tests use a fake LLM, so they need no API key. The runner
integration test starts a local HTTP server and runs real Playwright. It is
skipped if Chromium is not installed.

## Known limitations

- `gemini-3.8-flash` is assumed to be the API model id for "Gemini 3.8 Flash".
  If your account uses a different id, change it in `.env` or the sidebar.
- State lives in memory only (`MemorySaver`), so a browser refresh or
  **Reset session** discards it.
- If a run times out on Windows, browser processes can be left behind; close
  them in Task Manager.
- The site snapshot captures only the landing page. The healer receives the
  failing page's ARIA snapshot so it can fix locators on deeper pages.
