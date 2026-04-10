#!/usr/bin/env python3
"""Get command - Fetch paper info, overview, metrics, full-text."""
import typer
import json
import sys
from typing import Optional

from client import AlphaXivClient, AlphaXivError
from utils.helpers import extract_version_id

app = typer.Typer(name="get", help="Fetch paper data from alphaXiv")


@app.command()
def overview(
    paper_id: str = typer.Argument(..., help="arXiv ID (e.g., 2204.04)"),
    language: str = typer.Option("en", "--lang", "-l", help="Language"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Save to file"),
):
    """Get paper overview (AI-generated summary)."""
    try:
        with AlphaXivClient() as client:
            info = client.resolve_paper(paper_id)
            if not info:
                print(f"Error: Paper not found: {paper_id}", file=sys.stderr)
                raise typer.Exit(1)

            version_id = extract_version_id(info)
            if not version_id:
                print(f"Error: No version ID found", file=sys.stderr)
                raise typer.Exit(1)

            overview_data = client.get_overview(version_id, language)

            if not overview_data:
                print(f"Error: No overview available for {paper_id}", file=sys.stderr)
                raise typer.Exit(1)

            if json_output:
                print(json.dumps(overview_data, indent=2))
            else:
                title = info.get("title", "Unknown")
                summary = overview_data.get("summary", {}).get("summary", "N/A") if isinstance(overview_data.get("summary"), dict) else overview_data.get("summary", "N/A")
                full = overview_data.get("overview", "")

                print(f"# {title}")
                print(f"arXiv: {paper_id}")
                print(f"\n## Summary\n{summary[:500]}...")
                print(f"\n## Overview\n{full[:1000]}...")
            if output:
                with open(output, "w") as f:
                    json.dump({"info": info, "overview": overview_data}, f, indent=2)
                print(f"\nSaved to: {output}")

    except AlphaXivError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1)


@app.command()
def metrics(
    paper_id: str = typer.Argument(..., help="arXiv ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
):
    """Get paper metrics (citations, views, etc.)."""
    try:
        with AlphaXivClient() as client:
            info = client.resolve_paper(paper_id)
            if not info:
                print(f"Error: Paper not found: {paper_id}", file=sys.stderr)
                raise typer.Exit(1)

            version_id = extract_version_id(info)
            if not version_id:
                print(f"Error: No version ID", file=sys.stderr)
                raise typer.Exit(1)

            metrics_data = client.get_metrics(version_id)

            if not metrics_data:
                print(f"No metrics available for {paper_id}")
                return

            if json_output:
                print(json.dumps(metrics_data, indent=2))
            else:
                title = info.get("title", "Unknown")
                print(f"# {title}")
                print(f"arXiv: {paper_id}")
                print(f"\n## Metrics")
                for key, value in metrics_data.items():
                    print(f"  {key}: {value}")

    except AlphaXivError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1)


@app.command()
def fulltext(
    paper_id: str = typer.Argument(..., help="arXiv ID"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Save to file"),
):
    """Get paper full text."""
    try:
        with AlphaXivClient() as client:
            info = client.resolve_paper(paper_id)
            if not info:
                print(f"Error: Paper not found: {paper_id}", file=sys.stderr)
                raise typer.Exit(1)

            version_id = extract_version_id(info)
            if not version_id:
                print(f"Error: No version ID", file=sys.stderr)
                raise typer.Exit(1)

            text = client.get_full_text(version_id)

            if not text:
                print(f"No full text available for {paper_id}")
                return

            if output:
                with open(output, "w") as f:
                    f.write(text)
                print(f"Saved to: {output}")
            else:
                print(text[:2000] + ("..." if len(text) > 2000 else ""))

    except AlphaXivError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1)


@app.command()
def info(
    paper_id: str = typer.Argument(..., help="arXiv ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
):
    """Get basic paper info."""
    try:
        with AlphaXivClient() as client:
            info = client.resolve_paper(paper_id)
            if not info:
                print(f"Error: Paper not found: {paper_id}", file=sys.stderr)
                raise typer.Exit(1)

            if json_output:
                print(json.dumps(info, indent=2))
            else:
                title = info.get("title", "Unknown")
                abstract = info.get("abstract", "N/A")
                authors = info.get("authors", [])
                version = extract_version_id(info) or "N/A"

                print(f"# {title}")
                print(f"Version: {version}")
                print(f"\n## Authors")
                if isinstance(authors, list):
                    print(", ".join(authors))
                else:
                    print(authors)
                print(f"\n## Abstract\n{abstract[:500]}...")

    except AlphaXivError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1)


@app.command()
def all(
    paper_id: str = typer.Argument(..., help="arXiv ID"),
    language: str = typer.Option("en", "--lang", "-l", help="Language for overview"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Save to file"),
):
    """Get all paper data (info + overview + metrics + resources)."""
    try:
        with AlphaXivClient() as client:
            print(f"Fetching all data for {paper_id}...")

            # Get basic info
            info = client.resolve_paper(paper_id)
            if not info:
                print(f"Error: Paper not found: {paper_id}", file=sys.stderr)
                raise typer.Exit(1)

            version_id = extract_version_id(info)
            if not version_id:
                print(f"Error: No version ID found", file=sys.stderr)
                raise typer.Exit(1)

            # Fetch all data
            overview_data = client.get_overview(version_id, language)
            metrics_data = client.get_metrics(version_id)
            resources_data = client.get_resources(version_id)

            result = {
                "info": info,
                "overview": overview_data,
                "metrics": metrics_data,
                "resources": resources_data
            }

            if output:
                with open(output, "w") as f:
                    json.dump(result, f, indent=2)
                print(f"Saved all data to: {output}")
            else:
                print(json.dumps(result, indent=2))

    except AlphaXivError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1)


@app.command()
def status(
    paper_id: str = typer.Argument(..., help="arXiv ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
):
    """Check overview generation status."""
    try:
        with AlphaXivClient() as client:
            info = client.resolve_paper(paper_id)
            if not info:
                print(f"Error: Paper not found: {paper_id}", file=sys.stderr)
                raise typer.Exit(1)

            version_id = extract_version_id(info)
            if not version_id:
                print(f"Error: No version ID found", file=sys.stderr)
                raise typer.Exit(1)

            status_data = client.get_overview_status(version_id)

            if not status_data:
                print(f"No overview status available for {paper_id}")
                return

            if json_output:
                print(json.dumps(status_data, indent=2))
            else:
                print(f"Overview Status for {paper_id}:")
                for key, value in status_data.items():
                    print(f"  {key}: {value}")

    except AlphaXivError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1)
