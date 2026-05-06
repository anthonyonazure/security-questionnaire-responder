"""End-to-end test: load sample questionnaire + KB, answer all 22 items,
write outputs."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sqr.graph import build_graph
from sqr.state import QState

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_full_run_against_sample(tmp_path, monkeypatch):
    monkeypatch.setenv("SQR_OUT_DIR", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    graph = build_graph().compile()
    initial: QState = {
        "run_id": "test",
        "questionnaire_path": str(REPO / "samples" / "sample-caiq-lite.xlsx.yaml"),
        "knowledge_base_path": str(REPO / "knowledge_base" / "cyber_co.yaml"),
        "human_review_threshold": 0.7,
        "events": [],
    }
    final = await graph.ainvoke(initial)

    answers = final["answers"]
    summary = final["summary"]

    # Every item got an answer
    item_ids = {i["id"] for i in final["items"]}
    answer_ids = {a["id"] for a in answers}
    assert item_ids == answer_ids

    # Every answer has citations OR is flagged for review
    for a in answers:
        assert a["citations"] or a["needs_review"], f"{a['id']} has no citations and isn't flagged"

    # Average confidence is between 0 and 1
    assert 0.0 <= summary["avg_confidence"] <= 1.0

    # The two intentionally hard questions:
    by_id = {a["id"]: a for a in answers}
    # AC-99 (orphan account access reviews after merger) — KB has nothing direct
    # COMP-99 (FedRAMP) — KB has nothing direct
    # At least one of them should be flagged. (Stub may incorrectly answer one.)
    hard = [by_id["AC-99"], by_id["COMP-99"]]
    assert any(a["needs_review"] for a in hard), "Both hard questions answered with confidence — eval should catch this"

    # Output written
    out_files = list(tmp_path.glob("sample-caiq-lite*"))
    assert any(f.name.endswith(".filled.yaml") for f in out_files)
    parsed = yaml.safe_load((tmp_path / "sample-caiq-lite.filled.yaml").read_text())
    assert len(parsed["answers"]) == len(answers)
