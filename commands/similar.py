#!/usr/bin/env python3
"""Similar command - Get similar papers with BFS traversal."""
import typer
import json
import sys
from typing import Optional
from collections import deque

from alphaxiv_cli.client import AlphaXivClient, AlphaXivError

app = typer.Typer(name="similar", help="Get similar papers")


@app.command()
def main(
    paper_id: str = typer.Argument(..., help="arXiv ID"),
    limit: int = typer.Option(10, "--limit", "-n", help="Similar papers per paper"),
    depth: int = typer.Option(1, "--depth", "-d", help="BFS depth (1-3)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Save to file"),
):
    """Get similar papers (optionally traverse BFS)."""
    papers = []
    results = {}
    try:
        with AlphaXivClient() as client:
            if depth == 1:
                papers = client.get_similar_papers(paper_id, limit)
                if json_output:
                    print(json.dumps(papers, indent=2))
                else:
                    info = client.resolve_paper(paper_id)
                    title = info.get("title", "Unknown") if info else "Unknown"
                    print(f"# Similar to: {title}")
                    print(f"arXiv: {paper_id}")
                    print(f"\n## Similar Papers ({len(papers)})\n")
                    for i, p in enumerate(papers, 1):
                        pid = p.get("universal_paper_id", p.get("paper_id", "N/A"))
                        ptitle = p.get("title", "N/A")[:60]
                        print(f"{i}. {ptitle}... [{pid}]")
            else:
                results = bfs_similar(client, paper_id, depth, limit)
                if json_output:
                    print(json.dumps(results, indent=2))
                else:
                    print(f"# Knowledge Graph from {paper_id}")
                    print(f"Depth: {depth}, Limit: {limit}")
                    print(f"\n## Papers Found: {len(results)}\n")
                    for pid, data in results.items():
                        title = data.get("title", "N/A")[:50]
                        level = data.get("depth", 0)
                        related = data.get("related_to", "N/A")
                        print(f"[{level}] {title}... [{pid}] (from: {related})")
            
            if output:
                with open(output, "w") as f:
                    if depth == 1:
                        json.dump({"paper": paper_id, "similar": papers}, f, indent=2)
                    else:
                        json.dump({"paper": paper_id, "graph": results}, f, indent=2)
                print(f"\nSaved to: {output}")
                
    except AlphaXivError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1)


def bfs_similar(client: AlphaXivClient, start_id: str, max_depth: int, limit: int):
    """BFS traversal to find similar papers at multiple levels."""
    visited = {start_id: {"title": "Start", "depth": 0, "related_to": None}}
    queue = deque([(start_id, 0)])
    
    while queue:
        current_id, depth = queue.popleft()
        
        if depth >= max_depth:
            continue
        
        try:
            similar = client.get_similar_papers(current_id, limit)
            
            for paper in similar:
                pid = paper.get("universal_paper_id", paper.get("paper_id"))
                if pid and pid not in visited:
                    visited[pid] = {
                        "title": paper.get("title", "N/A"),
                        "depth": depth + 1,
                        "related_to": current_id
                    }
                    queue.append((pid, depth + 1))
                    
        except AlphaXivError as e:
            print(f"Warning: Failed to get similar for {current_id}: {e}", file=sys.stderr)
    
    return visited
