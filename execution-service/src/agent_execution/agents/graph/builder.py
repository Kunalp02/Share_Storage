from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agent_execution.agents.graph.context import AgentGraphContext
from agent_execution.agents.graph.nodes import AgentGraphNodes
from agent_execution.agents.graph.routing import route_after_llm
from agent_execution.agents.graph.state import AgentGraphState


def build_execution_graph(context: AgentGraphContext):
    nodes = AgentGraphNodes(context)
    graph = StateGraph(AgentGraphState)
    graph.add_node("prepare_context", nodes.prepare_context)
    graph.add_node("call_llm", nodes.call_llm)
    graph.add_node("run_tools", nodes.run_tools)
    graph.add_node("finalize_answer", nodes.finalize_answer)
    graph.add_node("persist_memory", nodes.persist_memory)
    graph.add_edge(START, "prepare_context")
    graph.add_edge("prepare_context", "call_llm")
    graph.add_conditional_edges(
        "call_llm",
        route_after_llm,
        {
            "run_tools": "run_tools",
            "finalize_answer": "finalize_answer",
            "persist_memory": "persist_memory",
        },
    )
    graph.add_edge("run_tools", "call_llm")
    graph.add_edge("finalize_answer", "persist_memory")
    graph.add_edge("persist_memory", END)
    return graph.compile()
