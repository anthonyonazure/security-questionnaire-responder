"""SQR LangGraph: load → answer-all → write_output → END."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from sqr.nodes import answer_all, load_inputs, write_output
from sqr.state import QState


def build_graph():
    g: StateGraph = StateGraph(QState)
    g.add_node("load_inputs", load_inputs)
    g.add_node("answer_all", answer_all)
    g.add_node("write_output", write_output)
    g.add_edge(START, "load_inputs")
    g.add_edge("load_inputs", "answer_all")
    g.add_edge("answer_all", "write_output")
    g.add_edge("write_output", END)
    return g
