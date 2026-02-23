"""LangGraph workflow assembly for V1 scaffold."""

from langgraph.graph import END, StateGraph

from agent_orchestrator.graph.nodes import execute, finalize, plan, retrieve, verify
from agent_orchestrator.graph.state import AgentState


def build_graph(*, max_graph_loops: int = 2):
    def _should_retry(state: AgentState) -> str:
        verification = state.get("verification", {})
        if verification.get("passed", False):
            return "done"
        retry_budget = int(state.get("retry_budget", max_graph_loops))
        if state.get("retry_count", 0) < retry_budget:
            return "retry"
        return "done"

    graph = StateGraph(AgentState)

    graph.add_node("plan", plan.run)
    graph.add_node("retrieve", retrieve.run)
    graph.add_node("execute", execute.run)
    graph.add_node("verify", verify.run)
    graph.add_node("finalize", finalize.run)

    graph.set_entry_point("plan")
    graph.add_edge("plan", "retrieve")
    graph.add_edge("retrieve", "execute")
    graph.add_edge("execute", "verify")
    graph.add_conditional_edges("verify", _should_retry, {"retry": "plan", "done": "finalize"})
    graph.add_edge("finalize", END)

    return graph.compile()
