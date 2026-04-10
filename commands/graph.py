#!/usr/bin/env python3
"""Graph command - Build Obsidian notes from paper knowledge graph."""
import logging
import typer
import json
import sys
import re
from typing import Optional
from collections import deque
from datetime import datetime
from pathlib import Path
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

logger = logging.getLogger(__name__)

from client import AlphaXivClient, AlphaXivError
from overview_generator import ensure_overview_generated, load_credentials
from utils.helpers import extract_version_id
from config import PALACE_PATH, KG_PATH
from storage.memory import upsert_paper, add_citation_triple, add_topic_triple

app = typer.Typer(name="graph", help="Build Obsidian knowledge graph")


@app.command()
def main(
    paper_id: str = typer.Argument(..., help="arXiv ID"),
    output_dir: str = typer.Option("output", "--output", "-o", help="Output directory"),
    iterations: int = typer.Option(3, "--iterations", "-n", help="BFS iterations"),
    limit: int = typer.Option(5, "--limit", "-l", help="Similar papers per paper"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    download_images: bool = typer.Option(False, "--images", help="Download images from overview"),
    secret_file: Optional[str] = typer.Option(None, "--secret", help="Path to SECRET.md with credentials"),
    headless: bool = typer.Option(False, "--headless/--no-headless", help="Run Playwright in headless mode (default: visible browser)"),
):
    """Build Obsidian notes with paper connections."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    reports_dir = output_path / "reports"
    images_dir = output_path / "images"
    db_file = output_path / "papers_db.json"
    db = load_db(db_file)
    
    try:
        with AlphaXivClient() as client:
            info = client.resolve_paper(paper_id)
            if not info:
                print(f"Error: Paper not found: {paper_id}", file=sys.stderr)
                raise typer.Exit(1)
            
            title = info.get("title", "Unknown")
            
            print(f"Building knowledge graph: {title}")
            print(f"Output: {output_dir}")
            print(f"Iterations: {iterations}, Limit: {limit}\n")
            
            count, pending = build_graph(
                client, paper_id, output_path, reports_dir, images_dir,
                db, db_file, iterations, limit, verbose, download_images,
                Path(secret_file) if secret_file else None, headless
            )
            
            print(f"\n✓ Generated {count} paper notes")
            if pending:
                print(f"  {pending} paper(s) skipped — see {output_dir}/pending_generation.json")
            
    except AlphaXivError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1)


def load_db(db_file: Path) -> dict:
    if db_file.exists():
        return json.loads(db_file.read_text())
    return {}


def save_db(db_file: Path, db: dict):
    db_file.write_text(json.dumps(db, indent=2))


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
    
    safe_id = sanitize_paper_id(paper_id)
    paper_images_dir = images_dir / safe_id
    
    if not paper_images_dir.resolve().is_relative_to(images_dir.resolve()):
        print(f"    WARNING: Path traversal attempt blocked for {paper_id}")
        return markdown
    
    paper_images_dir.mkdir(parents=True, exist_ok=True)
    
    for alt_text, url in matches:
        if url.startswith('http'):
            try:
                resp = httpx.get(url, timeout=30, follow_redirects=True)
                if resp.status_code == 200:
                    content_type = resp.headers.get('content-type', '').lower()
                    
                    if not content_type.startswith('image/'):
                        print(f"    Skipping non-image content: {content_type}")
                        continue
                    
                    if len(resp.content) > 10 * 1024 * 1024:
                        print(f"    Skipping large image (>10MB)")
                        continue
                    
                    ext_map = {
                        'image/jpeg': '.jpeg',
                        'image/jpg': '.jpg',
                        'image/png': '.png',
                        'image/gif': '.gif',
                        'image/webp': '.webp',
                        'image/svg+xml': '.svg',
                    }
                    ext = ext_map.get(content_type, Path(url).suffix or '.png')
                    
                    safe_name = re.sub(r'[^\w\-]', '_', alt_text[:30]) if alt_text else f"img_{hash(url) % 10000}"
                    filename = f"{safe_name}{ext}"
                    img_path = paper_images_dir / filename
                    
                    if not img_path.resolve().is_relative_to(paper_images_dir.resolve()):
                        print(f"    WARNING: Path traversal blocked for filename: {filename}")
                        continue
                    
                    img_path.write_bytes(resp.content)
                    
                    local_path = f"./images/{safe_id}/{filename}"
                    markdown = markdown.replace(url, local_path)
                    print(f"    Downloaded image: {filename}")
            except Exception as e:
                print(f"    Failed to download image: {e}")
    
    return markdown


def sanitize_paper_id(paper_id: str) -> str:
    safe_id = re.sub(r'[^\w\-\.]', '_', paper_id)
    return safe_id[:255]


def build_graph(client, start_id, output_dir, reports_dir, images_dir, db, db_file, iterations, limit, verbose, download_imgs, secret_path=None, headless=True):
    """Build knowledge graph with BFS traversal."""
    queue = deque([(start_id, 0, None)])
    processed = 0
    iteration = 0
    today = datetime.now().strftime("%Y-%m-%d")
    pending_file = output_dir / "pending_generation.json"
    pending = load_db(pending_file)

    credentials = load_credentials(secret_path)
    has_credentials = bool(credentials[0] and credentials[1])
    
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
                
                version_id = extract_version_id(info)
                if not version_id:
                    progress.advance(task)
                    continue
                
                try:
                    overview = client.get_overview(version_id)
                except Exception as e:
                    if verbose:
                        print(f"  No overview for {paper_id}: {e}")
                    overview = None
                    
                    if has_credentials:
                        if verbose:
                            print(f"  Attempting to generate overview for {paper_id}...")
                        if ensure_overview_generated(paper_id, version_id, client, secret_path, headless):
                            try:
                                overview = client.get_overview(version_id)
                            except Exception as e2:
                                logger.warning(f"Failed to fetch overview after generation for {paper_id}: {e2}")
                                overview = None
                    
                    if not overview or not overview.get('overview'):
                        pending[paper_id] = {
                            "title": info.get("title", ""),
                            "reason": "no_credentials" if not has_credentials else "generation_failed",
                            "date": today,
                        }
                        save_db(pending_file, pending)
                
                if not overview or not overview.get('overview'):
                    if verbose:
                        print(f"  Skipping {paper_id} - no overview available")
                    progress.advance(task)
                    continue
                
                similar = client.get_similar_papers(paper_id, limit)
                
                note, report = build_note(paper_id, info, overview, similar, today, db, images_dir, download_imgs)
                
                safe_id = sanitize_paper_id(paper_id)
                note_path = output_dir / f"{safe_id}.md"
                
                if not note_path.resolve().is_relative_to(output_dir.resolve()):
                    raise ValueError(f"Path traversal detected: {paper_id}")
                
                note_path.write_text(note)
                
                if report:
                    reports_dir.mkdir(parents=True, exist_ok=True)
                    report_path = reports_dir / f"{safe_id}_report.md"
                    
                    if not report_path.resolve().is_relative_to(reports_dir.resolve()):
                        raise ValueError(f"Path traversal detected in report: {paper_id}")
                    
                    report_path.write_text(report)
                    if verbose:
                        print(f"  Created intermediate report: {paper_id}_report.md")
                
                db[paper_id] = {"title": info.get("title", ""), "processed": True, "date": today}
                processed += 1
                
                upsert_paper(paper_id, info, overview, PALACE_PATH)
                for c in overview.get("citations", []):
                    cited_id = c.get("arxivId") or c.get("arxiv_id") or c.get("paper_id")
                    if cited_id:
                        add_citation_triple(paper_id, cited_id, KG_PATH)
                for topic in extract_keywords(overview, info)[:5]:
                    add_topic_triple(paper_id, topic, KG_PATH)
                
                if processed % 10 == 0:
                    save_db(db_file, db)
                
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
    
    save_db(db_file, db)
    return processed, len(pending)


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
    
    all_tags = keywords
    
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
