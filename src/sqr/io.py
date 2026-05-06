"""Read questionnaires + write filled responses.

Supports two formats:
  - YAML (sample format) — simple in/out
  - XLSX — typical real-world questionnaire format. Reads the first sheet,
    expects an `id` and `question` column; writes `answer`, `confidence`,
    `citations`, and `needs_review` columns to a sibling output file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


def load_items(path: Path) -> list[dict[str, Any]]:
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(path.read_text())["items"]
    if path.suffix == ".xlsx":
        from openpyxl import load_workbook

        wb = load_workbook(path)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        header = [str(c).strip().lower() if c else "" for c in rows[0]]
        col_id = header.index("id") if "id" in header else 0
        col_q = header.index("question") if "question" in header else 1
        col_cat = header.index("category") if "category" in header else None
        col_fmt = header.index("answer_format") if "answer_format" in header else None
        items = []
        for row in rows[1:]:
            if not row or row[col_id] is None:
                continue
            items.append({
                "id": str(row[col_id]),
                "question": str(row[col_q] or ""),
                "category": str(row[col_cat]) if col_cat is not None and row[col_cat] else "",
                "answer_format": str(row[col_fmt]) if col_fmt is not None and row[col_fmt] else "free_text",
            })
        return items
    raise ValueError(f"unsupported questionnaire file type: {path.suffix}")


def load_knowledge(path: Path) -> list[dict[str, Any]]:
    return yaml.safe_load(path.read_text())["knowledge"]


def write_responses(
    *, source_path: Path, answers: list[dict], output_dir: Path
) -> Path:
    """Write the filled questionnaire alongside the source as YAML + JSON.
    For XLSX inputs, also write a filled XLSX next to the YAML."""
    output_dir.mkdir(parents=True, exist_ok=True)
    base = output_dir / source_path.stem

    yaml_path = base.with_suffix(".filled.yaml")
    yaml_path.write_text(yaml.safe_dump({"answers": answers}, sort_keys=False))

    json_path = base.with_suffix(".filled.json")
    json_path.write_text(json.dumps(answers, indent=2, default=str))

    if source_path.suffix == ".xlsx":
        from openpyxl import load_workbook
        from openpyxl.styles import PatternFill

        wb = load_workbook(source_path)
        ws = wb.active
        # Add answer columns if missing
        header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=False))
        existing_headers = [c.value for c in header_row]
        next_col = len(existing_headers) + 1
        new_cols = ["answer", "citations", "confidence", "needs_review"]
        for i, col_name in enumerate(new_cols):
            ws.cell(row=1, column=next_col + i, value=col_name)

        # Build a id → answer map
        by_id = {a["id"]: a for a in answers}

        review_fill = PatternFill(start_color="FFF7CC", end_color="FFF7CC", fill_type="solid")
        for row in ws.iter_rows(min_row=2):
            row_id = str(row[0].value or "").strip()
            ans = by_id.get(row_id)
            if not ans:
                continue
            row[next_col - 1].value = ans.get("answer", "")
            row[next_col].value = ", ".join(ans.get("citations") or [])
            row[next_col + 1].value = round(ans.get("confidence", 0), 2)
            row[next_col + 2].value = "yes" if ans.get("needs_review") else "no"
            if ans.get("needs_review"):
                for c in row:
                    c.fill = review_fill

        xlsx_path = base.with_suffix(".filled.xlsx")
        wb.save(xlsx_path)

    return yaml_path
