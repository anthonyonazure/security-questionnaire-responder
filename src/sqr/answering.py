"""Generate one answer per questionnaire item, citing KB entries.

Two-pass design:
  1. Retrieve top KB entries for the question (lexical + topic-tag).
  2. Compose answer with the LLM, constrained to:
        - Cite the specific KB entry ids actually used
        - Emit a confidence score 0.0-1.0
        - Refuse to fabricate; if no KB support, return needs_review=True

Stub fallback (no API key): a deterministic heuristic that matches on
top-1 retrieval result. The eval harness uses it as a baseline."""

from __future__ import annotations

import json
import os

from anthropic import AsyncAnthropic

MODEL = os.environ.get("SQR_MODEL", "claude-sonnet-4-6")


_PROMPT = """You are answering one item on a vendor security questionnaire as the security engineering lead at a B2B cybersecurity services company.

Question (id={item_id}, format={answer_format}, category={category}):
{question}

Knowledge base entries the retriever surfaced (use ONLY these — do not invent facts):
{kb_block}

Rules:
1. Cite the specific KB entry ids you use. If you can't ground the answer in
   at least one KB entry, set needs_review=true with confidence ≤ 0.4.
2. Match the requested answer_format:
   - "yes_no": just "Yes" or "No" (one word)
   - "yes_no_explain": "Yes." or "No." then 1-3 sentences of explanation
   - "free_text": 1-3 paragraph factual answer
3. Confidence: 0.9+ when multiple KB entries align; 0.7 when one entry directly
   answers; 0.5 when entries are tangentially relevant; ≤0.4 when nothing in
   the KB answers the question.
4. Never use marketing language. Reviewers will read this.

Output ONLY a JSON object:
{{
  "answer": "...",
  "citations": ["KB-IAM-MFA", "KB-IAM-SSO"],
  "confidence": 0.92,
  "needs_review": false,
  "reasoning": "one short sentence on which entries you used"
}}"""


def _stub_answer(item: dict, kb_hits: list[dict]) -> dict:
    """Deterministic fallback when no API key is set."""
    if not kb_hits:
        return {
            "answer": "(no knowledge-base support — needs human review)",
            "citations": [],
            "confidence": 0.2,
            "needs_review": True,
            "reasoning": "retriever returned no KB entries for this question",
        }
    top = kb_hits[0]
    statement = top["statement"].strip()
    fmt = item.get("answer_format", "free_text")
    if fmt == "yes_no":
        # For yes_no in stub mode, default to "Yes" if KB hit; reviewer will check.
        return {
            "answer": "Yes",
            "citations": [top["id"]],
            "confidence": 0.55,
            "needs_review": True,
            "reasoning": f"yes_no in stub mode — flagged for review; cited {top['id']}",
        }
    if fmt == "yes_no_explain":
        return {
            "answer": f"Yes. {statement.split(chr(10))[0]}",
            "citations": [top["id"]],
            "confidence": 0.7,
            "needs_review": False,
            "reasoning": f"top KB hit {top['id']}",
        }
    return {
        "answer": statement,
        "citations": [h["id"] for h in kb_hits[:2]],
        "confidence": 0.65 if len(kb_hits) >= 2 else 0.55,
        "needs_review": len(kb_hits) < 2,
        "reasoning": f"composed from {len(kb_hits)} KB hit(s)",
    }


async def answer_item(item: dict, kb_hits: list[dict]) -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return _stub_answer(item, kb_hits)

    if not kb_hits:
        return {
            "answer": "(no knowledge-base support — needs human review)",
            "citations": [],
            "confidence": 0.2,
            "needs_review": True,
            "reasoning": "retriever returned no KB entries",
        }

    kb_block = "\n\n".join(f"[{e['id']}] {e['statement'].strip()}" for e in kb_hits)
    prompt = _PROMPT.format(
        item_id=item["id"],
        answer_format=item.get("answer_format", "free_text"),
        category=item.get("category", "(unspecified)"),
        question=item["question"],
        kb_block=kb_block,
    )

    client = AsyncAnthropic()
    msg = await client.messages.create(
        model=MODEL,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0].strip()
    parsed = json.loads(text)
    return parsed
