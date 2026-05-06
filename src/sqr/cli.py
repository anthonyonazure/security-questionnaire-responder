"""Typer CLI: sqr run --questionnaire <file> [--kb <file>]."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

import structlog
import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from sqr.graph import build_graph
from sqr.state import QState

load_dotenv()

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()
log = structlog.get_logger()


@app.command()
def run(
    questionnaire: str = typer.Option(..., "--questionnaire", "-q", help="YAML or XLSX questionnaire"),
    kb: str = typer.Option(None, "--kb", help="Knowledge base YAML"),
    threshold: float = typer.Option(None, "--threshold", help="Confidence cutoff for human review (0-1)"),
) -> None:
    """Auto-answer a vendor security questionnaire from the knowledge base."""
    asyncio.run(_run(questionnaire, kb, threshold))


async def _run(q_path: str, kb_path: str | None, threshold: float | None) -> None:
    run_id = uuid.uuid4().hex[:10]
    initial: QState = {
        "run_id": run_id,
        "questionnaire_path": q_path,
        "knowledge_base_path": kb_path or os.environ.get("SQR_KNOWLEDGE_BASE", "knowledge_base/cyber_co.yaml"),
        "human_review_threshold": threshold if threshold is not None else float(os.environ.get("SQR_HUMAN_REVIEW_THRESHOLD", "0.7")),
        "events": [],
    }
    graph = build_graph().compile()
    console.rule(f"[bold cyan]SQR run {run_id}[/]")

    final: QState = {}
    async for event in graph.astream(initial, stream_mode="values"):
        final = event
        last = (event.get("events") or [{}])[-1]
        if last:
            console.print(f"  [green]✓[/] {last.get('kind', '?')}")

    answers = final.get("answers") or []
    table = Table(show_header=True, box=None)
    table.add_column("ID", width=10)
    table.add_column("Category", width=22)
    table.add_column("Confidence", width=10)
    table.add_column("Review?", width=8)
    table.add_column("Citations")
    for a in answers:
        review = "[yellow]YES[/]" if a.get("needs_review") else "[green]no[/]"
        cites = ", ".join(a.get("citations") or []) or "—"
        conf = f"{a.get('confidence', 0):.2f}"
        table.add_row(a["id"], a.get("category") or "", conf, review, cites)

    console.rule("[bold cyan]Result[/]")
    console.print(table)
    s = final.get("summary") or {}
    console.print(
        f"\n[bold]{s.get('auto_complete', 0)}[/] auto-answered · "
        f"[bold yellow]{s.get('needs_review', 0)}[/] need review · "
        f"avg confidence [bold]{s.get('avg_confidence', 0)}[/]"
    )
    console.print(f"[dim]Output: {final.get('output_path')}[/]")

    out = Path("out") / f"{run_id}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(final, default=str, indent=2))


@app.command()
def version() -> None:
    """Print version."""
    from sqr import __version__
    console.print(f"security-questionnaire-responder {__version__}")


if __name__ == "__main__":
    app()
