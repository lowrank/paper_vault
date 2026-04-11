#!/usr/bin/env python3
"""Explore command - Full knowledge graph exploration."""
import logging
import typer
import json
import sys
from typing import Optional
from collections import deque
from datetime import datetime

from alphaxiv_cli.client import AlphaXivClient, AlphaXivError

app = typer.Typer(name="explore", help="Explore paper connections deeply")

logger = logging.getLogger(__name__)


@app.command()
def main(
    paper_id: str = typer.Argument(..., help="arXiv ID"),
    depth: int = typer.Option(3, "--depth", "-d", help="Exploration depth (1-5)"),
    limit: int = typer.Option(5, "--limit", "-n", help="Similar papers per paper"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Save to file"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Explore paper connections (similar + similar-of-similar)."""
    try:
        with AlphaXivClient() as client:
            info = client.resolve_paper(paper_id)
            if not info:
                print(f"Error: Paper not found: {paper_id}", file=sys.stderr)
                raise typer.Exit(1)
            
            title = info.get("title", "Unknown")
            
            if verbose:
                print(f"Exploring from: {title} [{paper_id}]")
                print(f"Depth: {depth}, Limit: {limit}\n")
            
            graph = explore_paper(client, paper_id, depth, limit, verbose)
            
            if json_output:
                print(json.dumps(graph, indent=2))
            else:
                print(f"# Knowledge Graph")
                print(f"Seed: {title}")
                print(f"arXiv: {paper_id}")
                print(f"\n## Papers Discovered: {len(graph)}\n")
                
                for pid, data in sorted(graph.items(), key=lambda x: (x[1].get("depth", 0), x[0])):
                    ptitle = data.get("title", "N/A")[:50]
                    pdepth = data.get("depth", 0)
                    similar = data.get("similar_count", 0)
                    prefix = "  " * pdepth + f"[D{pdepth}]"
                    print(f"{prefix} {ptitle}... ({similar} similar)")
            
            if output:
                output_data = {
                    "seed": {"id": paper_id, "title": title},
                    "explored": datetime.now().isoformat(),
                    "graph": graph
                }
                with open(output, "w") as f:
                    json.dump(output_data, f, indent=2)
                print(f"\nSaved to: {output}")
                
    except AlphaXivError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1)


def explore_paper(client: AlphaXivClient, start_id: str, max_depth: int, limit: int, verbose: bool = False):
    """Explore paper connections using BFS."""
    graph = {start_id: {"title": "Loading...", "depth": 0, "similar": [], "similar_count": 0}}
    queue = deque([(start_id, 0)])
    visited = {start_id}
    
    try:
        info = client.resolve_paper(start_id)
        if info:
            graph[start_id]["title"] = info.get("title", "Unknown")
    except AlphaXivError as e:
        logger.warning(f"Could not resolve paper {start_id}: {e}")
    
    while queue:
        current_id, depth = queue.popleft()
        
        if depth >= max_depth:
            continue
        
        if verbose:
            print(f"  " * depth + f"→ {current_id} (depth={depth})")
        
        try:
            similar = client.get_similar_papers(current_id, limit)
            
            for paper in similar:
                pid = paper.get("universal_paper_id", paper.get("paper_id"))
                if not pid:
                    continue
                    
                if pid not in visited:
                    visited.add(pid)
                    graph[pid] = {
                        "title": paper.get("title", "N/A"),
                        "depth": depth + 1,
                        "similar": [],
                        "similar_count": 0
                    }
                    queue.append((pid, depth + 1))
                
                if pid in graph:
                    graph[pid]["similar"].append(current_id)
            
            if current_id in graph:
                graph[current_id]["similar_count"] = len(similar)
                
        except AlphaXivError as e:
            if verbose:
                print(f"  " * depth + f"  Error: {e}")
    
    return graph
