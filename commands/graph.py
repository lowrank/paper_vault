#!/usr/bin/env python3
"""Graph command - Build Obsidian notes from paper knowledge graph."""
import typer
import json
import sys
import re
from typing import Optional
from collections import deque
from datetime import datetime
from pathlib import Path
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from alphaxiv_cli.client import AlphaXivClient, AlphaXivError
from alphaxiv_cli.overview_generator import ensure_overview_generated, is_playwright_available

app = typer.Typer(name="graph", help="Build Obsidian knowledge graph")


@app.command()
def main(
    paper_id: str = typer.Argument(..., help="arXiv ID"),
    output_dir: str = typer.Option("output", "--output", "-o", help="Output directory"),
    iterations: int = typer.Option(3, "--iterations", "-n", help="BFS iterations"),
    limit: int = typer.Option(5, "--limit", "-l", help="Similar papers per paper"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    download_images: bool = typer.Option(False, "--images", help="Download images from overview"),
    generate_missing: bool = typer.Option(False, "--generate", "-g", help="Auto-generate missing overviews (requires Playwright + credentials)"),
    secret_file: Optional[str] = typer.Option(None, "--secret", help="Path to SECRET.md with credentials"),
    headless: bool = typer.Option(False, "--headless/--no-headless", help="Run Playwright in headless mode (default: visible browser)"),
):
    """Build Obsidian notes with paper connections."""
    client = AlphaXivClient()
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    reports_dir = output_path / "reports"
    images_dir = output_path / "images"
    db_file = output_path / "papers_db.json"
    db = load_db(db_file)
    
    try:
        info = client.resolve_paper(paper_id)
        if not info:
            print(f"Error: Paper not found: {paper_id}", file=sys.stderr)
            raise typer.Exit(1)
        
        title = info.get("title", "Unknown")
        
        print(f"Building knowledge graph: {title}")
        print(f"Output: {output_dir}")
        print(f"Iterations: {iterations}, Limit: {limit}\n")
        
        count = build_graph(
            client, paper_id, output_path, reports_dir, images_dir,
            db, db_file, iterations, limit, verbose, download_images,
            generate_missing, Path(secret_file) if secret_file else None, headless
        )
        
        print(f"\n✓ Generated {count} paper notes")
        
    except AlphaXivError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1)
    finally:
        client.close()


def load_db(db_file: Path) -> dict:
    if db_file.exists():
        return json.loads(db_file.read_text())
    return {}


def save_db(db_file: Path, db: dict):
    db_file.write_text(json.dumps(db, indent=2))


def get_arxiv_categories(paper_id: str) -> list:
    """Get arXiv subject classifications."""
    import httpx
    try:
        resp = httpx.get(f'https://export.arxiv.org/api/query?id_list={paper_id}', timeout=10)
        if resp.status_code == 200:
            cats = re.findall(r'<category term="([^"]+)"', resp.text)
            filtered = []
            for c in cats:
                if c.startswith(('math.', 'physics.', 'cs.', 'stat.', 'q-bio.', 'q-fin.', 'econ.')):
                    filtered.append(c.replace('.', '-'))
            return filtered
    except:
        pass
    return []


def extract_keywords(overview: Optional[dict], paper_info: Optional[dict] = None) -> list:
    """Extract keywords from overview and paper info."""
    topics = []
    if paper_info and 'topics' in paper_info:
        topics.extend(paper_info.get('topics', []))
    if overview:
        if 'topics' in overview:
            topics.extend(overview.get('topics', []))
        ai_tooltips = overview.get('aiTooltips', [])
        if ai_tooltips:
            for tip in ai_tooltips:
                if isinstance(tip, dict) and 'name' in tip:
                    topics.append(tip['name'])
    return list(set(topics))[:10]


def download_images_from_markdown(markdown: str, paper_id: str, images_dir: Path) -> str:
    """Download images from markdown and update references."""
    import httpx
    
    img_pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
    matches = re.findall(img_pattern, markdown)
    
    if not matches:
        return markdown
    
    paper_images_dir = images_dir / paper_id
    paper_images_dir.mkdir(parents=True, exist_ok=True)
    
    for alt_text, url in matches:
        if url.startswith('http'):
            try:
                resp = httpx.get(url, timeout=30)
                if resp.status_code == 200:
                    ext = Path(url).suffix or '.png'
                    safe_name = re.sub(r'[^\w\-]', '_', alt_text[:30]) if alt_text else f"img_{hash(url) % 10000}"
                    filename = f"{safe_name}{ext}"
                    img_path = paper_images_dir / filename
                    
                    img_path.write_bytes(resp.content)
                    
                    local_path = f"./images/{paper_id}/{filename}"
                    markdown = markdown.replace(url, local_path)
                    print(f"    Downloaded image: {filename}")
            except Exception as e:
                print(f"    Failed to download image: {e}")
    
    return markdown


def build_graph(client, start_id, output_dir, reports_dir, images_dir, db, db_file, iterations, limit, verbose, download_imgs, generate_missing=False, secret_path=None, headless=True):
    """Build knowledge graph with BFS traversal."""
    queue = deque([(start_id, 0, None)])
    processed = 0
    iteration = 0
    today = datetime.now().strftime("%Y-%m-%d")
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
    ) as progress:
        
        while queue and iteration < iterations:
            current_batch_size = len(queue)
            task = progress.add_task(
                f"[cyan]Iteration {iteration + 1}/{iterations} - Processing {current_batch_size} papers",
                total=current_batch_size
            )
            
            new_queue = deque()
            
            while queue:
                paper_id, depth, related_to = queue.popleft()
                
                if paper_id in db:
                    if verbose:
                        print(f"  [skip] {paper_id} (already processed)")
                    progress.advance(task)
                    continue
                
                if verbose:
                    print(f"  [{depth}] Processing: {paper_id} (related_to={related_to})")
                
                info = client.resolve_paper(paper_id)
                if not info:
                    if verbose:
                        print(f"  Failed to resolve: {paper_id}")
                    progress.advance(task)
                    continue
                
                version_id = info.get("versionId") or info.get("version_id")
                if not version_id:
                    progress.advance(task)
                    continue
                
                try:
                    overview = client.get_overview(version_id)
                except Exception as e:
                    if verbose:
                        print(f"  No overview for {paper_id}: {e}")
                    overview = None
                    
                    # Try to generate overview if flag is set
                    if generate_missing and overview is None:
                        if verbose:
                            print(f"  Attempting to generate overview for {paper_id}...")
                        if ensure_overview_generated(paper_id, version_id, client, secret_path, headless):
                            try:
                                overview = client.get_overview(version_id)
                            except:
                                overview = None
                
                if not overview or not overview.get('overview'):
                    if verbose:
                        print(f"  Skipping {paper_id} - no overview available")
                    progress.advance(task)
                    continue
                
                similar = client.get_similar_papers(paper_id, limit)
                
                note, report = build_note(paper_id, info, overview, similar, today, db, images_dir, download_imgs)
                
                note_path = output_dir / f"{paper_id}.md"
                note_path.write_text(note)
                
                if report:
                    reports_dir.mkdir(parents=True, exist_ok=True)
                    report_path = reports_dir / f"{paper_id}_report.md"
                    report_path.write_text(report)
                    if verbose:
                        print(f"  Created intermediate report: {paper_id}_report.md")
                
                db[paper_id] = {"title": info.get("title", ""), "processed": True, "date": today}
                save_db(db_file, db)
                
                processed += 1
                
                if depth < iterations - 1:
                    for sp in similar[:limit]:
                        spid = sp.get("universal_paper_id") or sp.get("paper_id")
                        if spid and spid not in db:
                            new_queue.append((spid, depth + 1, paper_id))
                
                title = info.get('title', '')[:40]
                progress.update(task, description=f"[green]✓ {paper_id}: {title}...")
                progress.advance(task)
            
            queue = new_queue
            iteration += 1
    
    return processed


def build_note(paper_id, info, overview, similar, today, db, images_dir, download_imgs) -> tuple:
    """Build Obsidian note with full formatting. Returns (note_content, report_content)."""
    title = info.get("title", "Unknown")
    abstract = info.get("abstract", "N/A")
    
    summary = ""
    if overview.get('summary') and isinstance(overview['summary'], dict):
        summary = overview['summary'].get('summary', '')
    
    full_overview = overview.get('overview', '')
    
    intermediate = overview.get('intermediateReport', '')
    has_report = bool(intermediate and isinstance(intermediate, str))
    
    citations = overview.get('citations', [])
    keywords = extract_keywords(overview, info)
    arxiv_cats = get_arxiv_categories(paper_id)
    
    all_tags = list(set(keywords + arxiv_cats))
    
    report_link = f"> [!tip] See Also\n> [[./reports/{paper_id}_report.md|Intermediate Report]]" if has_report else ""
    
    md = f"""---
date: {today}
tags: [{', '.join(all_tags)}]
arxiv: {paper_id}
---

# {title}

> [!abstract] Summary
> {summary}

{report_link}

> [!note] Abstract
> {abstract}

## Full Overview
{full_overview if full_overview else 'N/A'}

## Key Citations

"""

    for c in citations:
        if isinstance(c, dict):
            cit_title = c.get('title', 'N/A')
            cit_full = c.get('fullCitation', '')
            cit_just = c.get('justification', '')
            md += f"> [!quote]\n> ### {cit_title}\n>\n> {cit_full}\n>\n> **Why important:** {cit_just}\n\n"
    
    if keywords:
        md += f"""## Topics

{', '.join(keywords)}

"""

    md += f"""## Related Papers ({len(similar[:5])})

"""
    
    for paper in similar[:5]:
        pid = paper.get('universal_paper_id', '')
        ptitle = paper.get('title', 'N/A')
        if pid:
            md += f"- [[{pid}.md|{ptitle}]]\n"
    
    md += """

---
*Generated from alphaXiv overview*
"""
    
    if download_imgs:
        md = download_images_from_markdown(md, paper_id, images_dir)
    
    report_md = None
    if has_report:
        report_md = f"""---
date: {today}
arxiv: {paper_id}
---

# {title}

## Intermediate Report

{intermediate}

---

> [!tip] Back to Overview
> [[../{paper_id}.md|{title}]]

---
*Generated from alphaXiv overview*
"""
    
    return md, report_md
