#!/usr/bin/env python3
"""AlphaXiv CLI - Main entry point."""
import typer
import json
import sys
from typing import Optional
from pathlib import Path

from client import AlphaXivClient, AlphaXivError
from commands import get_cmd, similar_cmd, explore_cmd, graph_cmd

app = typer.Typer(
    name="axiv",
    help="AlphaXiv CLI - Interact with alphaXiv API and explore paper connections"
)

app.add_typer(get_cmd.app, name="get")
app.add_typer(similar_cmd.app, name="similar")
app.add_typer(explore_cmd.app, name="explore")
app.add_typer(graph_cmd.app, name="graph")


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
):
    """Search papers by keyword."""
    client = AlphaXivClient()
    try:
        results = client.search(query, limit)
        if json_output:
            print(json.dumps(results, indent=2))
        else:
            if not results:
                print("No results found")
                return
            for i, paper in enumerate(results, 1):
                title = paper.get("title", "N/A")[:60]
                pid = paper.get("universal_paper_id", paper.get("paper_id", "N/A"))
                print(f"{i}. {title}... [{pid}]")
    except AlphaXivError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1)
    finally:
        client.close()


@app.command()
def version():
    """Show version."""
    from __init__ import __version__
    print(f"alphaxiv-cli {__version__}")


if __name__ == "__main__":
    app()
