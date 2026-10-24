"""Streamlit UI for the Phase 1 (cold start) POC.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import os
import traceback
import uuid
from pathlib import Path

import streamlit as st
from langgraph.types import Command

from config import (
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_PROVIDER,
    SITES,
    SUPPORTED_PROVIDERS,
    custom_site,
    execution_timeout_seconds,
)
from graph import RECURSION_LIMIT, build_graph, initial_state
from ui import render
from ui.gate_cards import GATE_CARDS

st.set_page_config(page_title="AI-native E2E · Phase 1 POC", page_icon="🧪", layout="wide")

API_KEY_VARS = {"gemini": ("GOOGLE_API_KEY", "GEMINI_API_KEY"), "openai": ("OPENAI_API_KEY",), "anthropic": ("ANTHROPIC_API_KEY",)}


# ------------------------------------------------------------------ session
def init_session() -> None:
    ss = st.session_state
    ss.setdefault("thread_id", uuid.uuid4().hex)
    ss.setdefault("activity", [])
    ss.setdefault("last_error", None)
    if "graph" not in ss:
        ss["graph"] = build_graph()


def reset_session() -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]


def run_config() -> dict:
    ss = st.session_state
    return {
        "configurable": {
            "thread_id": ss["thread_id"],
            "llm_provider": ss.get("llm_provider", DEFAULT_LLM_PROVIDER),
            "llm_model": ss.get("llm_model", DEFAULT_LLM_MODEL),
            "auto_run": ss.get("auto_run", False),
            "headed": ss.get("headed", False),
            "timeout_seconds": ss.get("timeout_seconds", execution_timeout_seconds()),
        },
        "recursion_limit": RECURSION_LIMIT,
    }


def graph_snapshot() -> tuple[dict, str | None, bool]:
    """Return (state values, pending gate name, stalled?)."""
    snap = st.session_state["graph"].get_state(run_config())
    values = snap.values or {}
    interrupts = [i.value for task in snap.tasks for i in task.interrupts]
    gate = interrupts[0].get("gate") if interrupts else None
    stalled = bool(snap.next) and not interrupts
    return values, gate, stalled


# ------------------------------------------------------------------ sidebar
def selected_site():
    key = st.session_state.get("site_key", next(iter(SITES)))
    if key == "custom":
        url = (st.session_state.get("custom_url") or "").strip()
        return custom_site(url) if url.startswith(("http://", "https://")) else None
    return SITES[key]


def render_sidebar(values: dict) -> None:
    run_active = bool(values)
    with st.sidebar:
        st.header("⚙️ Configuration")

        st.subheader("Target site")
        options = [*SITES, "custom"]
        st.selectbox(
            "Demo site",
            options,
            format_func=lambda k: "Custom URL…" if k == "custom" else SITES[k].name,
            key="site_key",
            disabled=run_active,
        )
        if st.session_state.get("site_key") == "custom":
            st.text_input("URL", key="custom_url", placeholder="http://localhost:3000", disabled=run_active)
        site = (values.get("target_site") if run_active else None) or (selected_site().to_dict() if selected_site() else None)
        if site:
            st.caption(f"🌐 {site['url']}")
            if site.get("description"):
                st.caption(site["description"])
            for var in (site.get("username_env"), site.get("password_env")):
                if var:
                    st.caption(
                        f"✅ `{var}` set" if os.getenv(var)
                        else f"➖ `{var}` not set (only needed if the site requires login)"
                    )
        elif st.session_state.get("site_key") == "custom":
            st.warning("Enter a URL starting with http:// or https://")
        if run_active:
            st.caption("Target is locked for this run. Reset to change it.")

        st.subheader("LLM")
        st.selectbox(
            "Provider",
            SUPPORTED_PROVIDERS,
            index=SUPPORTED_PROVIDERS.index(DEFAULT_LLM_PROVIDER) if DEFAULT_LLM_PROVIDER in SUPPORTED_PROVIDERS else 0,
            key="llm_provider",
        )
        st.text_input("Model", value=DEFAULT_LLM_MODEL, key="llm_model")
        key_vars = API_KEY_VARS.get(st.session_state.get("llm_provider", ""), ())
        if key_vars and not any(os.getenv(v) for v in key_vars):
            st.warning(f"`{key_vars[0]}` is not set in .env")
        st.caption("Changes apply from the next agent call.")

        st.subheader("Execution")
        st.toggle("Auto-run generated code", key="auto_run", help="Skip the review step before generated code first runs.")
        st.toggle("Headed browser", key="headed")
        st.number_input("Run timeout (s)", min_value=30, max_value=1800, value=execution_timeout_seconds(), step=30, key="timeout_seconds")

        st.divider()
        st.button("🔄 Reset session", on_click=reset_session, width="stretch")
        st.caption(f"Session `{st.session_state['thread_id'][:8]}`")


# --------------------------------------------------------------- requirement
def render_requirement_input(values: dict) -> None:
    st.markdown("### 0 · Requirement")
    if values:
        with st.expander(f"Requirement (source: {values.get('requirement_source', 'text')})", expanded=False):
            st.text(values.get("raw_requirement", ""))
        return

    text = st.text_area(
        "Paste the business requirement",
        key="req_text",
        height=200,
        placeholder="As a registered user I want to log in with my username and password so that…",
    )
    upload = st.file_uploader("…or upload a .txt / .md file", type=["txt", "md"], key="req_file")
    file_text = upload.getvalue().decode("utf-8", errors="replace") if upload else ""
    if upload and text.strip():
        st.caption("Both provided: the pasted text and the file content will be combined.")
    requirement = "\n\n".join(part for part in (text.strip(), file_text.strip()) if part)

    site = selected_site()
    if st.button("🚀 Start Phase 1", type="primary", disabled=not requirement or site is None):
        st.session_state["activity"] = []
        st.session_state["last_error"] = None
        st.session_state["command"] = {
            "type": "start",
            "state": initial_state(requirement, upload.name if upload else "text", site.to_dict()),
        }
        st.rerun()


# ------------------------------------------------------------------ stages
def render_stage(placeholder, key: str, title: str, values: dict, gate: str | None) -> None:
    status = render.stage_status(values, key, gate)
    container = placeholder.container()
    if status == "pending" and not _has_content(values, key):
        return
    container.markdown(f"### {render.STATUS_ICON[status]} {title}")
    with container:
        render.RENDERERS[key](values)


def _has_content(values: dict, key: str) -> bool:
    return bool(
        {
            "interpretation": values.get("interpretation"),
            "scenarios": values.get("scenarios"),
            "test_cases": values.get("test_cases"),
            "code": values.get("generated_code") or values.get("site_context"),
            "self_repair": values.get("execution_results"),
            "baseline": values.get("baseline_approved"),
        }[key]
    )


def render_all(placeholders: dict, values: dict, gate: str | None) -> None:
    placeholders["stepper"].empty()
    with placeholders["stepper"].container():
        render.render_stepper(values, gate)
    for key, title, _ in render.STAGES:
        render_stage(placeholders[key], key, title, values, gate)
    placeholders["log"].empty()
    with placeholders["log"].container():
        render.render_orchestrator_log(values)


# ------------------------------------------------------------------ running
def execute(command: dict, placeholders: dict) -> None:
    graph = st.session_state["graph"]
    config = run_config()
    if command["type"] == "start":
        graph_input = command["state"]
    elif command["type"] == "resume":
        graph_input = Command(resume=command["value"])
    else:  # continue after an error / interrupted script run
        graph_input = None

    activity: list[str] = st.session_state["activity"]
    with placeholders["status"].container():
        with st.status("Running pipeline…", expanded=True) as status:
            try:
                for chunk in graph.stream(graph_input, config, stream_mode="updates"):
                    for node, update in chunk.items():
                        if node == "__interrupt__":
                            continue
                        if node == "orchestrator":
                            nxt = (update or {}).get("next_node")
                            reason = (update or {}).get("history", [{}])[-1].get("reason", "")
                            line = f"🧭 Orchestrator → **{render.label(nxt)}** — {reason}"
                            status.update(label=f"Running: {render.label(nxt)}…")
                        else:
                            line = f"✅ **{render.label(node)}** — {render.summarize_update(node, update)}"
                        activity.append(line)
                        status.markdown(line)
                    values, gate, _ = graph_snapshot()
                    render_all(placeholders, values, None)
                status.update(label="Paused — waiting for you" if graph_snapshot()[1] else "Pipeline finished", state="complete")
            except Exception as exc:  # surfaced with a retry button
                st.session_state["last_error"] = {"message": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()}
                activity.append(f"💥 Error: {type(exc).__name__}: {exc}")
                status.update(label="Error — see below", state="error")


# ------------------------------------------------------------------ main
def main() -> None:
    init_session()
    values, gate, stalled = graph_snapshot()
    command = st.session_state.get("command")
    interactive = command is None

    render_sidebar(values)

    st.title("🧪 AI-native E2E · Phase 1 — Cold Start")
    st.caption(
        "Requirement → interpretation → scenarios → test cases → Playwright code → self-repair → approved baseline. "
        "Humans approve at gates; the AI may change *how* a test navigates, never *what* it validates."
    )

    placeholders = {"stepper": st.empty(), "status": st.empty()}

    if interactive and st.session_state["activity"]:
        with placeholders["status"].container():
            with st.expander("Latest pipeline activity", expanded=False):
                for line in st.session_state["activity"][-40:]:
                    st.markdown(line)

    if values.get("halted_reason"):
        st.error(f"⛔ Run ended: {values['halted_reason']}. Use **Reset session** in the sidebar to start again.")

    error = st.session_state.get("last_error")
    if interactive and (error or stalled):
        with st.container(border=True):
            if error:
                st.error(f"The last step failed: {error['message']}")
                with st.expander("Traceback"):
                    st.code(error["trace"], language="text")
            else:
                st.warning("The pipeline stopped before reaching a gate (for example, the page was refreshed mid-run).")
            if st.button("▶️ Retry / continue from last checkpoint", type="primary"):
                st.session_state["last_error"] = None
                st.session_state["command"] = {"type": "continue"}
                st.rerun()

    render_requirement_input(values)

    for key, _, _ in render.STAGES:
        placeholders[key] = st.empty()
        if interactive and gate and GATE_CARDS.get(gate, ("",))[0] == key:
            GATE_CARDS[gate][1](values, len(values.get("history") or []))
        if interactive and key == "baseline" and values.get("final_artifacts"):
            render_downloads(values)

    with st.expander("🧭 Orchestrator log", expanded=False):
        placeholders["log"] = st.empty()

    render_all(placeholders, values, gate if interactive else None)

    if command is not None:
        st.session_state.pop("command", None)
        execute(command, placeholders)
        st.rerun()


def render_downloads(values: dict) -> None:
    files = values["final_artifacts"]["files"]
    cols = st.columns(len(files))
    for col, (name, path) in zip(cols, files.items()):
        if Path(path).exists():
            col.download_button(f"⬇️ {name}", Path(path).read_bytes(), file_name=name, key=f"dl_{name}", width="stretch")


main()
