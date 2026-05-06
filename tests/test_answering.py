import pytest

from sqr.answering import answer_item


@pytest.mark.asyncio
async def test_no_kb_hits_flags_review():
    item = {"id": "X", "question": "Random question", "answer_format": "free_text"}
    ans = await answer_item(item, [])
    assert ans["needs_review"] is True
    assert ans["confidence"] <= 0.4
    assert ans["citations"] == []


@pytest.mark.asyncio
async def test_stub_yes_no_explain_emits_yes_with_citation():
    item = {"id": "X", "question": "Q", "answer_format": "yes_no_explain"}
    kb = [{"id": "KB-1", "topics": [], "statement": "We do this thing daily."}]
    ans = await answer_item(item, kb)
    assert ans["answer"].startswith("Yes")
    assert "KB-1" in ans["citations"]
    assert ans["confidence"] >= 0.5


@pytest.mark.asyncio
async def test_stub_yes_no_flagged_for_review():
    item = {"id": "X", "question": "Q", "answer_format": "yes_no"}
    kb = [{"id": "KB-1", "topics": [], "statement": "yes"}]
    ans = await answer_item(item, kb)
    # yes_no in stub mode is uncertain — always review
    assert ans["needs_review"] is True


@pytest.mark.asyncio
async def test_stub_free_text_uses_two_kb_hits_when_available():
    item = {"id": "X", "question": "Q", "answer_format": "free_text"}
    kb = [
        {"id": "KB-1", "topics": [], "statement": "Statement A."},
        {"id": "KB-2", "topics": [], "statement": "Statement B."},
    ]
    ans = await answer_item(item, kb)
    assert "KB-1" in ans["citations"]
    assert "KB-2" in ans["citations"]
    assert ans["needs_review"] is False
