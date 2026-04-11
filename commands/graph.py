#!/usr/bin/env python3
"""Graph command - Build Obsidian notes from paper knowledge graph."""
from __future__ import annotations

import hashlib
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

from alphaxiv_cli.client import AlphaXivClient, AlphaXivError, has_overview_content
from alphaxiv_cli.overview_generator import ensure_overview_generated, is_session_valid
from alphaxiv_cli.utils.helpers import extract_version_id
from alphaxiv_cli.config import DEFAULT_CACHE_DIR
from alphaxiv_cli.context import get_context
from alphaxiv_cli.storage.memory import upsert_paper, add_citation_triple, add_topic_triple
from alphaxiv_cli.storage.cache import Cache

_cat_cache: Optional[Cache] = None


def _get_cat_cache() -> Cache:
    """Lazily initialise the category cache (avoids mkdir at import time)."""
    global _cat_cache
    if _cat_cache is None:
        _cat_cache = Cache(cache_dir=DEFAULT_CACHE_DIR, ttl_hours=24 * 30)
    return _cat_cache

app = typer.Typer(name="graph", help="Build Obsidian knowledge graph")


@app.command()
def main(
    paper_id: str = typer.Argument(..., help="arXiv ID"),
    output_dir: str = typer.Option("output", "--output", "-o", help="Output directory"),
    iterations: int = typer.Option(3, "--iterations", "-n", help="BFS iterations"),
    limit: int = typer.Option(5, "--limit", "-l", help="Similar papers per paper"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    download_images: bool = typer.Option(False, "--images", help="Download images from overview"),
    headless: bool = typer.Option(True, "--headless/--no-headless", help="Run overview-generation browser in headless mode (default: headless)"),
):
    """
    Build Obsidian notes with BFS paper connections.

    For papers that already have an AI overview on alphaxiv the note is
    generated immediately.  For papers without one, browser automation
    triggers generation using the saved login session (run `axiv login`
    once to save the session).
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    reports_dir = output_path / "reports"
    images_dir  = output_path / "images"
    db_file     = output_path / "papers_db.json"
    db          = load_db(db_file)

    try:
        with AlphaXivClient() as client:
            info = client.resolve_paper(paper_id)
            if not info:
                print(f"Error: Paper not found: {paper_id}", file=sys.stderr)
                raise typer.Exit(1)

            title = info.get("title", "Unknown")
            session_ok = is_session_valid()

            print(f"Building knowledge graph: {title}")
            print(f"Output: {output_dir}")
            print(f"Iterations: {iterations}, Limit: {limit}")
            if not session_ok:
                print("  Note: no valid alphaxiv session — papers without overviews will be skipped.")
                print("  Run `axiv login` to save a session and enable overview generation.")
            print()

            count, pending = build_graph(
                client, paper_id, output_path, reports_dir, images_dir,
                db, db_file, iterations, limit, verbose, download_images,
                session_ok, headless,
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
    topics = []
    if paper_info:
        raw = paper_info.get('topics')
        if isinstance(raw, list):
            topics.extend(raw)
    if overview:
        raw = overview.get('topics')
        if isinstance(raw, list):
            topics.extend(raw)
        ai_tooltips = overview.get('aiTooltips')
        if isinstance(ai_tooltips, list):
            for tip in ai_tooltips:
                if isinstance(tip, dict) and 'name' in tip:
                    topics.append(tip['name'])
    if not topics:
        summary_text = ''
        if isinstance((overview or {}).get('summary'), dict):
            summary_text = (overview or {}).get('summary', {}).get('summary', '')
        if not summary_text:
            summary_text = (overview or {}).get('intermediateReport', '') or ''
        topics = _keywords_from_text(
            (paper_info or {}).get('title', ''),
            summary_text[:2000],
        )
    return list(dict.fromkeys(t for t in topics if t))[:10]


_STOPWORDS = {
    'a', 'an', 'the', 'of', 'in', 'on', 'at', 'to', 'for', 'with', 'and',
    'or', 'is', 'are', 'was', 'be', 'by', 'as', 'from', 'that', 'this',
    'it', 'its', 'we', 'our', 'their', 'which', 'both', 'also', 'can',
    'has', 'have', 'been', 'into', 'not', 'such', 'well', 'under',
    'paper', 'work', 'study', 'research', 'approach', 'method', 'model',
    'based', 'show', 'using', 'used', 'propose', 'proposed',
    'university', 'researchers', 'authors', 'establishes', 'demonstrates',
    'provides', 'present', 'presents', 'results', 'data', 'problems',
}

def _keywords_from_text(title: str, summary: str) -> list:
    combined = f"{title}. {summary}"
    words = re.findall(r'\b[A-Za-z][a-z]{2,}\b', combined)
    
    bigrams = []
    for i in range(len(words) - 1):
        w1, w2 = words[i].lower(), words[i+1].lower()
        if w1 not in _STOPWORDS and w2 not in _STOPWORDS:
            bigrams.append(f"{words[i]} {words[i+1]}")
    
    freq: dict = {}
    for bg in bigrams:
        freq[bg] = freq.get(bg, 0) + 1
    
    ranked = sorted(freq, key=lambda k: -freq[k])
    return ranked[:10] if ranked else [w for w in words if w.lower() not in _STOPWORDS and len(w) > 4][:10]


def download_images_from_markdown(markdown: str, paper_id: str, images_dir: Path) -> str:
    """Download images from markdown and update references."""
    import httpx as _httpx
    
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
                resp = _httpx.get(url, timeout=30, follow_redirects=True)
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
                    
                    safe_name = re.sub(r'[^\w\-]', '_', alt_text[:30]) if alt_text else f"img_{hashlib.md5(url.encode()).hexdigest()[:8]}"
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
    if not paper_id:
        return "unknown"
    safe_id = re.sub(r'[^\w\-\.]', '_', paper_id)
    return safe_id[:255]


def get_arxiv_categories(paper_id: str) -> list:
    import httpx as _httpx
    import time
    cache = _get_cat_cache()
    cache_key = f"arxiv_cats:{paper_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    for attempt in range(3):
        try:
            r = _httpx.get(f"https://arxiv.org/abs/{paper_id}", timeout=15)
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            labels = re.findall(r'<span class="primary-subject">([^<]+)</span>', r.text)
            labels += re.findall(r'<span class="secondary-subject">([^<]+)</span>', r.text)
            codes = re.findall(r'context=([a-z]+\.[A-Z]+)', r.text)
            # also extract short codes embedded in labels like "Analysis of PDEs (math.AP)"
            for label in labels:
                m = re.search(r'\(([a-z]+\.[A-Z]+)\)', label)
                if m:
                    codes.append(m.group(1))
            result = list(dict.fromkeys(codes))
            cache.set(cache_key, result)
            return result
        except Exception as e:
            logger.debug(f"Failed to fetch arxiv categories for {paper_id}: {e}")
            time.sleep(1)
    return []


def build_graph(
    client, start_id, output_dir, reports_dir, images_dir,
    db, db_file, iterations, limit, verbose, download_imgs,
    session_ok=False, headless=True,
):
    """
    BFS traversal: generate Obsidian notes for a paper and its neighbours.

    session_ok  — True if a valid alphaxiv login session exists (from `axiv login`).
                  When False, papers without existing overviews are skipped.
    """
    ctx          = get_context()
    palace_path  = ctx.palace_dir
    kg_path      = ctx.kg_db

    queue        = deque([(start_id, 0, None)])
    processed    = 0
    iteration    = 0
    today        = datetime.now().strftime("%Y-%m-%d")
    pending_file = output_dir / "pending_generation.json"
    pending      = load_db(pending_file)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
    ) as progress:

        while queue and iteration < iterations:
            current_batch_size = len(queue)
            task = progress.add_task(
                f"[cyan]Iteration {iteration + 1}/{iterations} — {current_batch_size} papers",
                total=current_batch_size,
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
                    print(f"  [{depth}] Processing: {paper_id}")

                info = client.resolve_paper(paper_id)
                if not info:
                    progress.advance(task)
                    continue

                version_id = extract_version_id(info)
                if not version_id:
                    progress.advance(task)
                    continue

                # --- fetch overview ---
                overview = None
                try:
                    overview = client.get_overview(version_id)
                except Exception:
                    pass

                # --- no overview: try generation if session is valid ---
                has_overview = has_overview_content(overview)
                if not has_overview and session_ok:
                    progress.stop()
                    if verbose:
                        print(f"  Requesting overview generation for {paper_id}…")
                    ok = ensure_overview_generated(
                        paper_id, version_id, client, headless=headless,
                    )
                    progress.start()
                    if ok:
                        try:
                            overview = client.get_overview(version_id)
                        except Exception:
                            pass

                has_overview = has_overview_content(overview)
                if not has_overview:
                    pending[paper_id] = {
                        "title": info.get("title", ""),
                        "reason": "no_session" if not session_ok else "generation_failed",
                        "date": today,
                    }
                    save_db(pending_file, pending)
                    if verbose:
                        print(f"  Skip {paper_id} — no overview")
                    progress.advance(task)
                    continue

                # --- build note ---
                similar    = client.get_similar_papers(paper_id, limit)
                categories = get_arxiv_categories(paper_id)
                note, report = build_note(
                    paper_id, info, overview, similar, today,
                    db, images_dir, download_imgs, categories,
                )

                safe_id   = sanitize_paper_id(paper_id)
                note_path = output_dir / f"{safe_id}.md"
                if not note_path.resolve().is_relative_to(output_dir.resolve()):
                    raise ValueError(f"Path traversal detected: {paper_id}")
                note_path.write_text(note)

                if report:
                    reports_dir.mkdir(parents=True, exist_ok=True)
                    report_path = reports_dir / f"{safe_id}_report.md"
                    if not report_path.resolve().is_relative_to(reports_dir.resolve()):
                        raise ValueError(f"Path traversal in report: {paper_id}")
                    report_path.write_text(report)
                    if verbose:
                        print(f"  Report: {safe_id}_report.md")

                db[paper_id] = {
                    "title": info.get("title", ""), "processed": True, "date": today,
                }
                processed += 1

                # --- persist to palace / KG ---
                upsert_paper(paper_id, info, overview, palace_path)
                for c in overview.get("citations", []):
                    cited_id = (
                        c.get("arxivId") or c.get("arxiv_id") or c.get("paper_id")
                        or _arxiv_id_from_link(c.get("alphaxivLink", ""))
                    )
                    if cited_id:
                        add_citation_triple(paper_id, cited_id, kg_path)
                for topic in extract_keywords(overview, info)[:5]:
                    add_topic_triple(paper_id, topic, kg_path)

                if processed % 10 == 0:
                    save_db(db_file, db)

                # --- enqueue neighbours ---
                if depth < iterations - 1:
                    for sp in similar[:limit]:
                        spid = sp.get("universal_paper_id") or sp.get("paper_id")
                        if spid and spid not in db:
                            new_queue.append((spid, depth + 1, paper_id))

                progress.update(
                    task,
                    description=f"[green]✓ {paper_id}: {info.get('title','')[:40]}",
                )
                progress.advance(task)

            queue     = new_queue
            iteration += 1

    save_db(db_file, db)
    return processed, len(pending)


def _arxiv_id_from_link(link: str) -> Optional[str]:
    """Extract arXiv ID from an alphaxiv URL like https://alphaxiv.Org/abs/15.03044v3."""
    if not link:
        return None
    m = re.search(r"/abs/([0-9]{4}\.[0-9]+)", link)
    return m.group(1) if m else None


def build_note(paper_id, info, overview, similar, today, db, images_dir, download_imgs, categories=None) -> tuple:
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
    
    all_tags = [c.replace('.', '-') for c in dict.fromkeys(categories or [])]
    
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
{intermediate if intermediate else (full_overview if full_overview else 'N/A')}

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
