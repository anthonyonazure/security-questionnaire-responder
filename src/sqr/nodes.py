"""LangGraph nodes for the SQR agent."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from sqr.answering import answer_item
from sqr.io import load_items, load_knowledge, write_responses
from sqr.retrieval import retrieve
from sqr.state import QState

log = structlog.get_logger()


def _event(kind: str, **detail: Any) -> dict[str, Any]:
    return {"at": datetime.now(UTC).isoformat(), "kind": kind, **detail}


async def load_inputs(state: QState) -> dict[str, Any]:
    items = load_items(Path(state["questionnaire_path"]))
    knowledge = load_knowledge(Path(state["knowledge_base_path"]))
    log.info("sqr.loaded", items=len(items), kb=len(knowledge))
    return {
        "items": items,
        "knowledge": knowledge,
        "events": [_event("inputs_loaded", items=len(items), kb=len(knowledge))],
    }


async def answer_all(state: QState) -> dict[str, Any]:
    items = state["items"]
    knowledge = state["knowledge"]
    threshold = state.get("human_review_threshold", 0.7)

    async def _one(item: dict) -> dict:
        hits = retrieve(item["question"], knowledge)
        ans = await answer_item(item, hits)
        # Force review when confidence is below threshold even if model didn't flag it
        if ans.get("confidence", 0) < threshold:
            ans["needs_review"] = True
        ans = {"id": item["id"], "category": item.get("category"), **ans}
        log.info(
            "sqr.answered",
            id=item["id"],
            conf=ans.get("confidence"),
            review=ans.get("needs_review"),
        )
        return ans

    answered = await asyncio.gather(*[_one(i) for i in items])
    review_count = sum(1 for a in answered if a.get("needs_review"))
    avg_conf = round(
        sum(a.get("confidence", 0) for a in answered) / max(len(answered), 1), 3
    )
    return {
        "answers": answered,
        "summary": {
            "total": len(answered),
            "needs_review": review_count,
            "auto_complete": len(answered) - review_count,
            "avg_confidence": avg_conf,
        },
        "events": [
            _event(
                "answered_all",
                total=len(answered),
                needs_review=review_count,
                avg=avg_conf,
            )
        ],
    }


async def write_output(state: QState) -> dict[str, Any]:
    out_dir = Path(os.environ.get("SQR_OUT_DIR", "responses"))
    out_path = write_responses(
        source_path=Path(state["questionnaire_path"]),
        answers=state["answers"],
        output_dir=out_dir,
    )
    log.info("sqr.written", path=str(out_path))
    return {
        "output_path": str(out_path),
        "events": [_event("written", path=str(out_path))],
    }
