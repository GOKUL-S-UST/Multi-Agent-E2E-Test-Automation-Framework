"""Builds the Phase 1 LangGraph.

Topology: every worker node returns to ``orchestrator``; a single conditional
edge from ``orchestrator`` routes to the node it selected (or END).

    START -> orchestrator -(route)-> {interpreter, gate0, scenario_generator, ...}
    <each node> -> orchestrator
"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from graph import gates, nodes
from graph.orchestrator import (
    CODE_GENERATOR,
    CONFIRM_RUN,
    COVERAGE_BUILDER,
    EXECUTOR,
    FINALIZE,
    GATE0,
    GATE1,
    GATE2,
    HEALER,
    INTERPRETER,
    ROUTABLE_NODES,
    SCENARIO_GENERATOR,
    SITE_EXPLORER,
    TEST_CASE_GENERATOR,
    orchestrator_node,
    route,
)
from graph.state import PipelineState
from llm import llm_client_from_config

ORCHESTRATOR = "orchestrator"
RECURSION_LIMIT = 100


def build_graph(checkpointer=None, llm_factory: nodes.LLMFactory = llm_client_from_config):
    agent_nodes = nodes.make_agent_nodes(llm_factory)
    workers = {
        INTERPRETER: agent_nodes["interpreter"],
        GATE0: gates.gate0_node,
        SCENARIO_GENERATOR: agent_nodes["scenario_generator"],
        TEST_CASE_GENERATOR: agent_nodes["test_case_generator"],
        COVERAGE_BUILDER: nodes.coverage_node,
        GATE1: gates.gate1_node,
        SITE_EXPLORER: nodes.site_explorer_node,
        CODE_GENERATOR: agent_nodes["code_generator"],
        CONFIRM_RUN: gates.confirm_run_node,
        EXECUTOR: nodes.executor_node,
        HEALER: agent_nodes["healer"],
        GATE2: gates.gate2_node,
        FINALIZE: nodes.finalize_node,
    }
    assert set(workers) == set(ROUTABLE_NODES)

    builder = StateGraph(PipelineState)
    builder.add_node(ORCHESTRATOR, orchestrator_node)
    for name, fn in workers.items():
        builder.add_node(name, fn)
        builder.add_edge(name, ORCHESTRATOR)
    builder.add_edge(START, ORCHESTRATOR)
    builder.add_conditional_edges(ORCHESTRATOR, route, {**{n: n for n in ROUTABLE_NODES}, END: END})
    return builder.compile(checkpointer=checkpointer or MemorySaver())
