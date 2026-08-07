"""Retrieve relevant knowledge-base entries for a given questionnaire item.

We use a simple lexical retriever (token overlap + topic-tag boost) rather
than embeddings: the KB is small (dozens of entries), every answer must
cite specific entry ids, and reviewers want to see the matching logic.
Embeddings can be added later as a second-stage reranker without changing
the agent's contract."""

from __future__ import annotations

import re
from collections import Counter

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "do",
    "for",
    "from",
    "have",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "we",
    "with",
    "you",
    "your",
}


def _tokens(text: str) -> list[str]:
    return [
        t
        for t in re.findall(r"[a-z0-9_]+", text.lower())
        if t not in _STOPWORDS and len(t) > 2
    ]


def retrieve(
    question: str,
    knowledge: list[dict],
    *,
    top_k: int = 4,
    topic_boost: float = 2.5,
) -> list[dict]:
    """Return up to top_k KB entries scored by token overlap + topic match."""
    q_tokens = Counter(_tokens(question))
    if not q_tokens:
        return []

    scored: list[tuple[float, dict]] = []
    for entry in knowledge:
        kb_tokens = Counter(_tokens(entry["statement"]))
        # Token overlap (Jaccard-ish)
        common = sum((q_tokens & kb_tokens).values())
        if common == 0 and not any(
            t in question.lower() for t in entry.get("topics", [])
        ):
            continue
        # Starts as a token-overlap count but accumulates fractional topic boosts.
        score = float(common)
        # Topic-tag boost: if a topic substring appears in the question, boost
        for topic in entry.get("topics", []):
            normalized = topic.replace("_", " ")
            if topic in question.lower() or normalized in question.lower():
                score += topic_boost
        scored.append((score, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in scored[:top_k]]
