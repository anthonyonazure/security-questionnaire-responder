"""LangGraph state for a questionnaire run."""

from __future__ import annotations

from operator import add
from typing import Annotated, Any, TypedDict


class QState(TypedDict, total=False):
    run_id: str
    questionnaire_path: str
    knowledge_base_path: str
    human_review_threshold: float

    items: list[dict[str, Any]]                  # parsed questions
    knowledge: list[dict[str, Any]]              # parsed KB

    answers: Annotated[list[dict[str, Any]], add]  # per-item: {id, answer, confidence, citations, needs_review}

    summary: dict[str, Any]                      # aggregate stats
    output_path: str | None                      # where the filled questionnaire lives

    events: Annotated[list[dict[str, Any]], add]
