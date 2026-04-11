#!/usr/bin/env python3
"""
Research command — structured paper-research workflow powered by a Memory Palace.

Sub-commands
------------
  start      <wing> <paper_id> [<paper_id>…]  Begin / resume a research session.
  expand     <wing>                           BFS-expand the wing by one hop.
  query      <wing> <question>               Semantic search inside a wing.
  walk       <wing> [--hall <hall>]          Walk through a hall and read drawers.
  synthesize <wing>                          Distil the wing into a synthesis note.
  visualize  <wing>                          Render the paper graph (PNG + HTML).
  status     [<wing>]                        Print palace / wing overview.
  wings                                      List all research wings.

Design — Memory Palace metaphor
--------------------------------
  WING    → a research topic / session (e.g. "score-matching-2024")
  HALL    → memory type corridor (facts / discoveries / questions / methods / context)
  ROOM    → one paper inside a wing
  CLOSET  → distilled summary of a room pointing to its drawers
  DRAWER  → verbatim content extracted from the paper
  TUNNEL  → cross-paper connection (citation, similarity)

The palace SQLite lives at ~/.alphaxiv/research_palace.sqlite3.
Semantic retrieval uses the same ChromaDB backend as storage.memory, but
with richer wing/hall metadata so searches are much more precise.
"""

import json
import logging
import sys
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional, List

import typer
from rich import print as rprint
from rich.console import Console
from rich.markup import escape as markup_escape
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table
from rich.tree import Tree

from alphaxiv_cli.client import AlphaXivClient, AlphaXivError
from alphaxiv_cli.context import get_context
from alphaxiv_cli.storage.memory import add_citation_triple, add_topic_triple
from alphaxiv_cli.storage.palace import (
    HALLS,
    add_paper_to_wing,
    add_tunnel,
    create_wing,
    get_all_note_links,
    get_hall_drawers,
    get_note_link,
    get_room,
    get_syntheses,
    get_tunnels,
    get_wing,
    list_rooms,
    list_wings,
    save_synthesis,
    search_palace,
    set_note_link,
    upsert_to_chroma,
    wing_status,
)
from alphaxiv_cli.utils.helpers import extract_version_id

logger = logging.getLogger(__name__)
console = Console()


def _ctx():
    """Resolve workspace context lazily at call time so CWD is respected."""
    return get_context()

def _palace_db():
    return _ctx().palace_db

def _palace_dir():
    return _ctx().palace_dir

def _kg_db():
    return _ctx().kg_db

def _notes_dir():
    return _ctx().notes_dir

def _reports_dir():
    return _ctx().reports_dir

app = typer.Typer(
    name="research",
    help="Structured research workflow: build a Memory Palace from papers.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Tab-completion callbacks
# ---------------------------------------------------------------------------

def _complete_wing(incomplete: str) -> list[str]:
    """Return wing names that start with the typed prefix."""
    try:
        from alphaxiv_cli.storage.palace import list_wings
        return [
            w["name"] for w in list_wings(_palace_db())
            if w["name"].startswith(incomplete)
        ]
    except Exception:
        return []


def _complete_hall(incomplete: str) -> list[str]:
    """Return hall names that start with the typed prefix."""
    from alphaxiv_cli.storage.palace import HALLS
    return [h for h in HALLS if h.startswith(incomplete)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    import re
    return re.sub(r"[^\w\-]", "-", text.lower())[:48].strip("-")


def _today() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def _fetch_paper(client: AlphaXivClient, paper_id: str, verbose: bool = False):
    """Resolve paper_id → (info, version_id, overview). Returns (None, None, None) on failure."""
    info = client.resolve_paper(paper_id)
    if not info:
        if verbose:
            console.print(f"  [yellow]WARNING[/yellow] could not resolve {paper_id}")
        return None, None, None

    version_id = extract_version_id(info)
    if not version_id:
        if verbose:
            console.print(f"  [yellow]WARNING[/yellow] no version_id for {paper_id}")
        return info, None, None

    try:
        overview = client.get_overview(version_id)
    except AlphaXivError as e:
        if verbose:
            console.print(f"  [dim]No overview for {paper_id}: {e}[/dim]")
        overview = None

    return info, version_id, overview


def _arxiv_id_from_citation(c: dict) -> Optional[str]:
    """
    Extract an arXiv ID from a citation object.
    The API never populates arxivId/arxiv_id/paper_id directly; the ID
    is encoded in the alphaxivLink field as
      https://alphaxiv.org/abs/<arxiv_id>   or
      https://alphaxiv.org/abs/<arxiv_id>v<N>
    """
    import re as _re
    # Try flat ID fields first (in case the API ever fills them)
    direct = c.get("arxivId") or c.get("arxiv_id") or c.get("paper_id")
    if direct:
        return direct
    link = c.get("alphaxivLink") or ""
    m = _re.search(r"/abs/([0-9]{4}\.[0-9]+)", link)
    return m.group(1) if m else None


def _ingest_paper(
    client: AlphaXivClient,
    wing_name: str,
    paper_id: str,
    verbose: bool,
) -> bool:
    """Fetch, ingest one paper into palace. Returns True on success."""
    info, version_id, overview = _fetch_paper(client, paper_id, verbose)
    if not info:
        return False

    title = info.get("title", paper_id)
    add_paper_to_wing(wing_name, paper_id, title, info, overview, _palace_db())
    upsert_to_chroma(wing_name, paper_id, info, overview, _palace_dir())

    # Citation tunnels — parse arxiv ID out of alphaxivLink
    for c in (overview or {}).get("citations", []):
        cited_id = _arxiv_id_from_citation(c)
        if cited_id:
            add_citation_triple(paper_id, cited_id, _kg_db())
            add_tunnel(wing_name, paper_id, wing_name, cited_id, "cites", _palace_db())

    for topic in info.get("topics", [])[:5]:
        if isinstance(topic, str) and topic:
            add_topic_triple(paper_id, topic, _kg_db())

    if verbose:
        console.print(f"  [green]✓[/green] {paper_id}: {title[:60]}")
    return True


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------

@app.command()
def start(
    wing: str = typer.Argument(..., help="Wing name (research topic slug, e.g. 'score-matching')", autocompletion=_complete_wing),
    paper_ids: List[str] = typer.Argument(..., help="One or more arXiv IDs to seed the wing"),
    topic: Optional[str] = typer.Option(None, "--topic", "-t", help="Human-readable topic description"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """
    Begin (or resume) a research session for a topic.

    Seeds the wing with the given papers, placing each one into the
    appropriate halls of the palace.

    Example
    -------
      axiv research start score-matching 2011.13456 2206.00364 --topic "Score-based generative models"
    """
    topic_str = topic or wing.replace("-", " ")
    create_wing(wing, topic_str, _palace_db())

    prior = get_wing(wing, _palace_db())
    action = "Resuming" if prior else "Starting"
    console.print(f"\n[bold cyan]{action} research wing:[/bold cyan] {wing}")
    console.print(f"[dim]Topic: {topic_str}[/dim]\n")

    ok = 0
    seed_set = set(paper_ids)
    with AlphaXivClient() as client:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Ingesting seed papers…", total=len(paper_ids))
            for pid in paper_ids:
                if _ingest_paper(client, wing, pid, verbose):
                    ok += 1
                    # Record tunnels between seed papers that appear in each
                    # other's similar-papers list — connects the seeds visually
                    try:
                        similar = client.get_similar_papers(pid, limit=20)
                        for sp in similar:
                            spid = sp.get("universal_paper_id") or sp.get("paper_id")
                            if spid and spid in seed_set and spid != pid:
                                add_tunnel(wing, pid, wing, spid, "similar", _palace_db())
                    except AlphaXivError:
                        pass
                progress.advance(task)

    console.print(f"\n[bold green]✓ {ok}/{len(paper_ids)} papers added to wing '{wing}'[/bold green]")
    console.print(f"\nNext steps:")
    console.print(f"  axiv research expand {wing}            # BFS-expand one hop")
    console.print(f"  axiv research query {wing} '<question>'  # semantic search")
    console.print(f"  axiv research synthesize {wing}        # generate synthesis note")
    console.print(f"  axiv research status {wing}            # wing overview\n")


# ---------------------------------------------------------------------------
# expand
# ---------------------------------------------------------------------------

@app.command()
def expand(
    wing: str = typer.Argument(..., help="Wing to expand", autocompletion=_complete_wing),
    limit: int = typer.Option(5, "--limit", "-l", help="Similar papers per paper"),
    hops: int = typer.Option(1, "--hops", help="BFS hops to add"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """
    BFS-expand a wing by following similar-paper links.

    For each paper already in the wing, this command fetches up to `--limit`
    similar papers and ingests them, then (if `--hops` > 1) repeats.

    Example
    -------
      axiv research expand score-matching --limit 3 --hops 2
    """
    w = get_wing(wing, _palace_db())
    if not w:
        console.print(f"[red]Wing '{wing}' not found. Run `axiv research start {wing} <ids>` first.[/red]")
        raise typer.Exit(1)

    status = wing_status(wing, _palace_db())
    existing_ids: set[str] = set()
    for hall_info in status.get("halls", {}).values():
        for p in hall_info.get("papers", []):
            existing_ids.add(p["paper_id"])

    if not existing_ids:
        console.print("[yellow]Wing has no papers yet. Run `start` first.[/yellow]")
        raise typer.Exit(1)

    console.print(f"\n[bold cyan]Expanding wing:[/bold cyan] {wing}")
    console.print(f"[dim]{len(existing_ids)} papers already present[/dim]\n")

    queue = deque([(pid, 0) for pid in existing_ids])
    visited = set(existing_ids)
    added = 0

    with AlphaXivClient() as client:
        for _hop in range(hops):
            next_batch = deque()
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
            ) as progress:
                task = progress.add_task(
                    f"[cyan]Hop {_hop + 1}/{hops} — fetching similar papers",
                    total=len(queue),
                )
                while queue:
                    pid, depth = queue.popleft()
                    try:
                        similar = client.get_similar_papers(pid, limit)
                    except AlphaXivError as e:
                        if verbose:
                            console.print(f"  [dim]similar failed for {pid}: {e}[/dim]")
                        progress.advance(task)
                        continue

                    for sp in similar:
                        spid = sp.get("universal_paper_id") or sp.get("paper_id")
                        if not spid or spid in visited:
                            continue
                        visited.add(spid)
                        if _ingest_paper(client, wing, spid, verbose):
                            add_tunnel(wing, pid, wing, spid, "similar", _palace_db())
                            added += 1
                        next_batch.append((spid, depth + 1))

                    progress.advance(task)
            queue = next_batch

    console.print(f"\n[bold green]✓ Added {added} new papers to wing '{wing}'[/bold green]\n")


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------

@app.command()
def query(
    wing: str = typer.Argument(..., help="Wing to search", autocompletion=_complete_wing),
    question: str = typer.Argument(..., help="Research question or keyword query"),
    hall: Optional[str] = typer.Option(None, "--hall", "-H",
        help=f"Restrict to a hall: {', '.join(HALLS)}",
        autocompletion=_complete_hall),
    n: int = typer.Option(8, "--top", "-n", help="Number of results"),
    all_wings: bool = typer.Option(False, "--all", "-a", help="Search across all wings"),
):
    """
    Semantic search inside a wing (or across all wings).

    Navigate from the palace entrance directly to the most relevant drawers.

    Example
    -------
      axiv research query score-matching "how is the score function estimated?"
      axiv research query score-matching "denoising" --hall hall_methods
    """
    w_arg = None if all_wings else wing

    if hall and hall not in HALLS:
        console.print(f"[red]Unknown hall '{hall}'. Choose from: {', '.join(HALLS)}[/red]")
        raise typer.Exit(1)

    results = search_palace(question, w_arg, hall, _palace_dir(), n=n)

    header = f"[bold cyan]Palace search:[/bold cyan] \"{question}\""
    if w_arg:
        header += f"  [dim](wing={w_arg})[/dim]"
    if hall:
        header += f"  [dim](hall={hall})[/dim]"
    console.print(f"\n{header}\n")

    if not results:
        console.print("[yellow]No results found. Try a different query or expand the wing.[/yellow]")
        return

    for i, r in enumerate(results, 1):
        paper_id = r.get("paper_id", "?")
        title    = r.get("title", "")
        doc      = r.get("document", "")
        dist     = r.get("distance")
        hall     = r.get("hall", "")
        # ChromaDB returns squared-L2 distance in [0,4]; convert to [0,1] similarity
        dist_str = f"  [dim]score={1 - dist/2:.2f}[/dim]" if isinstance(dist, float) else ""
        hall_str = f"  [dim]{hall}[/dim]" if hall else ""

        body = doc[:400] + "…" if len(doc) > 400 else doc
        console.print(Panel(
            f"[bold]{markup_escape(title or paper_id)}[/bold] [dim][{paper_id}][/dim]{hall_str}{dist_str}\n\n{markup_escape(body)}",
            title=f"#{i}",
            border_style="dim",
        ))


# ---------------------------------------------------------------------------
# walk
# ---------------------------------------------------------------------------

@app.command()
def walk(
    wing: str = typer.Argument(..., help="Wing name", autocompletion=_complete_wing),
    hall: str = typer.Option(
        "hall_context",
        "--hall", "-H",
        help=f"Which hall to walk: {', '.join(HALLS)}",
        autocompletion=_complete_hall,
    ),
    paper_id: Optional[str] = typer.Option(None, "--paper", "-p", help="Walk only this paper's room"),
):
    """
    Walk through a hall and read the drawers.

    Think of this as strolling down a corridor in your memory palace,
    opening each room door and peering into its closet/drawers.

    Example
    -------
      axiv research walk score-matching --hall hall_methods
      axiv research walk score-matching --hall hall_facts --paper 2206.00364
    """
    if hall not in HALLS:
        console.print(f"[red]Unknown hall. Choose from: {', '.join(HALLS)}[/red]")
        raise typer.Exit(1)

    drawers = get_hall_drawers(wing, hall, _palace_db())
    if not drawers:
        console.print(f"[yellow]Hall '{hall}' in wing '{wing}' is empty.[/yellow]")
        return

    if paper_id:
        drawers = [d for d in drawers if d["paper_id"] == paper_id]
        if not drawers:
            console.print(f"[yellow]No drawers for paper {paper_id} in {hall}.[/yellow]")
            return

    from alphaxiv_cli.storage.palace import _HALL_DISPLAY
    console.print(f"\n[bold cyan]Walking:[/bold cyan] wing={wing} / {_HALL_DISPLAY.get(hall, hall)}\n")

    current_paper = None
    for d in drawers:
        if d["paper_id"] != current_paper:
            current_paper = d["paper_id"]
            console.print(f"\n[bold magenta]Room: {current_paper}[/bold magenta]")
        console.print(f"  [dim][{d['label']}][/dim]  {markup_escape(d['content'][:300])}")


# ---------------------------------------------------------------------------
# synthesize
# ---------------------------------------------------------------------------

@app.command()
def synthesize(
    wing: str = typer.Argument(..., help="Wing to synthesize", autocompletion=_complete_wing),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Save synthesis to this file"),
):
    """
    Distil the entire wing into a structured synthesis note.

    Walks every hall, collects closet summaries and key drawers, and writes
    a Markdown document that bridges all papers in the wing.

    Example
    -------
      axiv research synthesize score-matching --output synthesis.md
    """
    status = wing_status(wing, _palace_db())
    if not status:
        console.print(f"[red]Wing '{wing}' not found.[/red]")
        raise typer.Exit(1)

    topic    = status.get("topic", wing)
    today    = _today()
    closets  = status.get("closets", [])
    halls    = status.get("halls", {})
    n_papers = len(closets)

    # Fetch note links once for the whole wing
    note_links = get_all_note_links(wing, _palace_db())
    n_linked = len(note_links)

    lines = [
        f"---",
        f"wing: {wing}",
        f"topic: {topic}",
        f"papers: {n_papers}",
        f"linked: {n_linked}",
        f"synthesized: {today}",
        f"---",
        "",
        f"# Research Synthesis: {topic}",
        "",
        f"> Wing `{wing}` — {n_papers} papers across {len(HALLS)} halls.",
        f"> Obsidian notes linked: {n_linked}/{n_papers}."
        + ("" if n_linked == n_papers else
           f" Run `axiv research link {wing}` to generate missing notes."),
        "",
        "---",
        "",
    ]

    # --- Closet map (visual index) ---
    lines += [
        "## Palace Map (Closets)",
        "",
        "Each line is one room's distilled closet. Notes marked [note] link to Obsidian.",
        "",
    ]
    for cl in closets:
        kw   = ", ".join(cl["keywords"][:5]) if cl["keywords"] else "—"
        nl   = note_links.get(cl["paper_id"])
        note_str = f"  [[{nl['note_path']}|note]]" if nl else ""
        rep_str  = f"  [[{nl['report_path']}|report]]" if nl and nl.get("report_path") else ""
        lines.append(
            f"- **{cl['paper_id']}**{note_str}{rep_str} `[{kw}]`  {cl['summary'][:160]}"
        )
    lines.append("")

    # --- Per-hall synthesis ---
    lines += ["---", "", "## Hall Synthesis", ""]

    from alphaxiv_cli.storage.palace import _HALL_DISPLAY
    for hall in HALLS:
        hall_info = halls.get(hall, {})
        papers_in_hall = hall_info.get("papers", [])
        if not papers_in_hall:
            continue
        display = _HALL_DISPLAY.get(hall, hall)
        lines += [
            f"### {display}",
            "",
            f"*{len(papers_in_hall)} paper(s) in this hall*",
            "",
        ]
        # Pull top drawers per paper
        drawers = get_hall_drawers(wing, hall, _palace_db())
        current = None
        for d in drawers[:40]:  # cap to keep note readable
            if d["paper_id"] != current:
                current = d["paper_id"]
                ptitle = next(
                    (p["title"] for p in papers_in_hall if p["paper_id"] == current), current
                )
                nl = note_links.get(current)
                note_ref   = f" [[{nl['note_path']}|note]]"     if nl                        else ""
                report_ref = f" [[{nl['report_path']}|report]]" if nl and nl.get("report_path") else ""
                lines += [f"#### {ptitle} `[{current}]`{note_ref}{report_ref}", ""]
            lines.append(f"- **{d['label']}**: {d['content'][:200]}")
        lines.append("")

    # --- Open questions ---
    q_drawers = get_hall_drawers(wing, "hall_questions", _palace_db())
    if q_drawers:
        lines += [
            "---",
            "",
            "## Open Questions Across the Wing",
            "",
        ]
        for d in q_drawers[:20]:
            lines.append(f"- [{d['paper_id']}] {d['content']}")
        lines.append("")

    # --- Tunnels (cross-paper links) ---
    all_tunnels: list[dict] = []
    for cl in closets:
        all_tunnels.extend(get_tunnels(wing, cl["paper_id"], _palace_db()))
    if all_tunnels:
        lines += [
            "---",
            "",
            "## Tunnels (Cross-paper Connections)",
            "",
        ]
        seen = set()
        for t in all_tunnels:
            key = (t["from_paper"], t["to_paper"], t["relation"])
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- `{t['from_paper']}` —[{t['relation']}]→ `{t['to_paper']}`")
        lines.append("")

    # --- Footer ---
    lines += [
        "---",
        "",
        f"*Synthesis generated {today} from wing `{wing}` of the AlphaXiv Research Palace.*",
    ]

    md = "\n".join(lines)

    # Persist
    save_synthesis(wing, md, _palace_db())

    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md)
        console.print(f"\n[bold green]✓ Synthesis saved to {output}[/bold green]")
    else:
        console.print(markup_escape(md))

    prev = get_syntheses(wing, _palace_db())
    console.print(f"\n[dim]{len(prev)} synthesis version(s) stored in palace.[/dim]\n")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@app.command()
def status(
    wing: Optional[str] = typer.Argument(None, help="Wing name (omit for global palace status)", autocompletion=_complete_wing),
    json_output: bool = typer.Option(False, "--json", "-j"),
):
    """
    Print a structured overview of the palace or a specific wing.

    Example
    -------
      axiv research status                     # all wings
      axiv research status score-matching      # one wing
      axiv research status score-matching --json
    """
    if wing:
        data = wing_status(wing, _palace_db())
        if not data:
            console.print(f"[red]Wing '{wing}' not found.[/red]")
            raise typer.Exit(1)

        if json_output:
            console.print(json.dumps(data, indent=2))
            return

        _print_wing_status(wing, data)
    else:
        wings = list_wings(_palace_db())
        if json_output:
            console.print(json.dumps(wings, indent=2))
            return
        _print_palace_status(wings)


def _print_palace_status(wings: list[dict]):
    if not wings:
        console.print("[yellow]No research wings yet. Run `axiv research start <wing> <id>`.[/yellow]")
        return

    console.print("\n[bold cyan]Research Palace — all wings[/bold cyan]\n")
    table = Table(
        "Wing", "Topic", "Papers", "Created",
        show_header=True, header_style="bold magenta",
    )
    for w in wings:
        table.add_row(
            w["name"],
            w["topic"][:50],
            str(w.get("paper_count", 0)),
            w["created_at"][:10],
        )
    console.print(table)
    console.print()


def _print_wing_status(wing: str, data: dict):
    console.print(f"\n[bold cyan]Wing:[/bold cyan] {wing}  [dim](topic: {data.get('topic','')})[/dim]")
    console.print(f"[dim]Created: {data.get('created_at', '?')}[/dim]\n")

    from alphaxiv_cli.storage.palace import _HALL_DISPLAY
    tree = Tree(f"[bold]{wing}[/bold]")
    for hall in HALLS:
        hall_data = data.get("halls", {}).get(hall, {})
        papers = hall_data.get("papers", [])
        display = _HALL_DISPLAY.get(hall, hall)
        branch = tree.add(f"[magenta]{display}[/magenta]  ({len(papers)} rooms)")
        for p in papers[:5]:
            branch.add(f"[dim]{p['paper_id']}[/dim]  {p['title'][:50]}")
        if len(papers) > 5:
            branch.add(f"[dim]… and {len(papers)-5} more[/dim]")

    console.print(tree)

    tunnels   = data.get("tunnel_count", 0)
    syntheses = data.get("synthesis_count", 0)
    console.print(f"\n[dim]Tunnels: {tunnels}  |  Syntheses: {syntheses}[/dim]\n")

    closets = data.get("closets", [])
    if closets:
        console.print("[bold]Closet index:[/bold]")
        for cl in closets:
            kw = ", ".join(cl["keywords"][:4]) if cl["keywords"] else "—"
            console.print(f"  [dim]{cl['paper_id']}[/dim]  [{kw}]  {markup_escape(cl['summary'][:100])}")
        console.print()


# ---------------------------------------------------------------------------
# visualize
# ---------------------------------------------------------------------------

@app.command()
def visualize(
    wing: str = typer.Argument(..., help="Wing to visualize", autocompletion=_complete_wing),
    output_dir: str = typer.Option("output", "--output", "-o", help="Directory for output files"),
    fmt: str = typer.Option("both", "--format", "-f",
        help="Output format: png | html | both"),
):
    """
    Render the paper graph for a wing as an interactive HTML file and/or PNG.

    Nodes are papers; edges are tunnels (similar / cites).
    Seed papers (added via `start`) are highlighted in a different colour.
    The HTML output is self-contained — open it in any browser, no server needed.

    Example
    -------
      axiv research visualize diffusion-models
      axiv research visualize diffusion-models --format html --output ./graphs
    """
    import sqlite3

    w = get_wing(wing, _palace_db())
    if not w:
        console.print(f"[red]Wing '{wing}' not found.[/red]")
        raise typer.Exit(1)

    conn = sqlite3.connect(str(_palace_db()))
    conn.row_factory = sqlite3.Row

    # All papers in the wing with their titles
    paper_rows = conn.execute(
        "SELECT DISTINCT paper_id, title FROM rooms WHERE wing_name=?", (wing,)
    ).fetchall()
    papers: dict[str, str] = {r["paper_id"]: r["title"] for r in paper_rows}

    # All tunnels
    tunnel_rows = conn.execute(
        "SELECT from_paper, to_paper, relation FROM tunnels "
        "WHERE from_wing=? OR to_wing=?", (wing, wing)
    ).fetchall()
    tunnels = [(r["from_paper"], r["to_paper"], r["relation"]) for r in tunnel_rows]

    # Identify seed papers (added first — they have the smallest room IDs)
    seed_ids_rows = conn.execute(
        "SELECT DISTINCT paper_id FROM rooms WHERE wing_name=? "
        "ORDER BY id ASC LIMIT 10", (wing,)
    ).fetchall()
    # Rough heuristic: any paper that is only a source (never a target) in tunnels
    # is a seed — or just take the first N added if no tunnels yet
    tunnel_targets = {t[1] for t in tunnels}
    seed_ids = {r["paper_id"] for r in seed_ids_rows if r["paper_id"] not in tunnel_targets}
    if not seed_ids:  # fallback: first 3 added
        seed_ids = {r["paper_id"] for r in seed_ids_rows[:3]}

    conn.close()

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    if fmt in ("png", "both"):
        _render_png(wing, papers, tunnels, seed_ids, out_path)
    if fmt in ("html", "both"):
        _render_html(wing, papers, tunnels, seed_ids, out_path)


def _short(title: str, pid: str, maxlen: int = 28) -> str:
    label = title if title else pid
    return label[:maxlen] + "…" if len(label) > maxlen else label


def _render_png(
    wing: str,
    papers: dict[str, str],
    tunnels: list[tuple],
    seed_ids: set[str],
    out_path: Path,
) -> None:
    try:
        import networkx as nx
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
    except ImportError as e:
        console.print(f"[yellow]PNG skipped — missing library: {e}[/yellow]")
        return

    G = nx.DiGraph()
    for pid, title in papers.items():
        G.add_node(pid, label=_short(title, pid))
    for src, dst, rel in tunnels:
        for external in (src, dst):
            if external not in G:
                G.add_node(external, label=external[:12])
        G.add_edge(src, dst, label=rel)

    pos = nx.spring_layout(G, seed=42, k=2.5)

    node_colors = [
        "#4e9af1" if n in seed_ids
        else "#a8d5a2" if n not in papers   # external citation target
        else "#f4a261"
        for n in G.nodes()
    ]
    labels = {n: G.nodes[n].get("label", n) for n in G.nodes()}

    fig, ax = plt.subplots(figsize=(14, 9))
    nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=1800, ax=ax, alpha=0.92)
    nx.draw_networkx_labels(G, pos, labels=labels, font_size=7, ax=ax)
    nx.draw_networkx_edges(
        G, pos, edge_color="#888", arrows=True,
        arrowstyle="-|>", arrowsize=18,
        connectionstyle="arc3,rad=0.08", ax=ax,
    )
    edge_labels = {(s, d): r for s, d, r in tunnels if s in G and d in G}
    nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=6, ax=ax)

    seed_patch    = mpatches.Patch(color="#4e9af1", label="Seed papers")
    expand_patch  = mpatches.Patch(color="#f4a261", label="Discovered via expand")
    ext_patch     = mpatches.Patch(color="#a8d5a2", label="External cited papers")
    ax.legend(handles=[seed_patch, expand_patch, ext_patch], loc="upper left", fontsize=8)
    ax.set_title(f"Research Palace — wing: {wing}", fontsize=13)
    ax.axis("off")
    plt.tight_layout()

    png_path = out_path / f"{wing}_graph.png"
    plt.savefig(png_path, dpi=150, bbox_inches="tight")
    plt.close()
    console.print(f"[bold green]✓ PNG saved:[/bold green] {png_path}")


def _render_html(
    wing: str,
    papers: dict[str, str],
    tunnels: list[tuple],
    seed_ids: set[str],
    out_path: Path,
) -> None:
    """
    Write a self-contained HTML file using vis-network (loaded from CDN).
    No Python dependency beyond the stdlib — the graph rendering is pure JS.
    """
    import json as _json

    nodes_js = []
    for pid, title in papers.items():
        label  = _short(title, pid, 32)
        color  = "#4e9af1" if pid in seed_ids else "#f4a261"
        border = "#1a5fa8" if pid in seed_ids else "#c97830"
        nodes_js.append({
            "id":    pid,
            "label": f"{label}\n{pid}",
            "title": title,
            "color": {"background": color, "border": border,
                      "highlight": {"background": "#ffe066", "border": "#c9a800"}},
            "font":  {"size": 11},
            "shape": "box",
        })
    # Add any tunnel endpoints (citation targets etc.) not already in the wing
    known = set(papers)
    for src, dst, rel in tunnels:
        for external in (src, dst):
            if external not in known:
                nodes_js.append({
                    "id":    external,
                    "label": external,
                    "title": f"External ({rel} target): {external}",
                    "color": {"background": "#c8e6c9", "border": "#388e3c",
                              "highlight": {"background": "#ffe066", "border": "#c9a800"}},
                    "font":  {"size": 9},
                    "shape": "ellipse",
                })
                known.add(external)

    edges_js = [
        {"from": src, "to": dst, "label": rel,
         "arrows": "to", "color": {"color": "#888"},
         "font": {"size": 9, "align": "middle"}}
        for src, dst, rel in tunnels
    ]

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>Research Palace — {wing}</title>
  <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
  <style>
    body {{ margin:0; font-family: sans-serif; background:#1a1a2e; color:#eee; }}
    #header {{ padding:12px 20px; background:#16213e; border-bottom:1px solid #0f3460; }}
    #header h2 {{ margin:0; font-size:1.1rem; color:#4e9af1; }}
    #header p  {{ margin:4px 0 0; font-size:.8rem; color:#aaa; }}
    #graph {{ width:100%; height:calc(100vh - 80px); }}
    #legend {{ position:absolute; top:90px; left:12px; background:rgba(22,33,62,.85);
               padding:8px 14px; border-radius:6px; font-size:.75rem; }}
    .dot {{ display:inline-block; width:10px; height:10px; border-radius:2px;
            margin-right:5px; vertical-align:middle; }}
  </style>
</head>
<body>
  <div id="header">
    <h2>Research Palace &mdash; wing: <em>{wing}</em></h2>
    <p>{len(papers)} papers &nbsp;|&nbsp; {len(tunnels)} tunnels &nbsp;|&nbsp;
       hover a node to see the full title &nbsp;|&nbsp; drag to rearrange</p>
  </div>
  <div id="legend">
    <span class="dot" style="background:#4e9af1"></span>Seed papers<br>
    <span class="dot" style="background:#f4a261"></span>Discovered via expand<br>
    <span class="dot" style="background:#c8e6c9"></span>External cited papers
  </div>
  <div id="graph"></div>
  <script>
    const nodes = new vis.DataSet({_json.dumps(nodes_js, indent=2)});
    const edges = new vis.DataSet({_json.dumps(edges_js, indent=2)});
    const container = document.getElementById("graph");
    const options = {{
      physics: {{
        solver: "forceAtlas2Based",
        forceAtlas2Based: {{ gravitationalConstant:-60, springLength:160, damping:.5 }},
        stabilization: {{ iterations: 200 }},
      }},
      interaction: {{ hover:true, tooltipDelay:100, navigationButtons:true, keyboard:true }},
      edges: {{ smooth: {{ type:"curvedCW", roundness:.15 }} }},
    }};
    new vis.Network(container, {{ nodes, edges }}, options);
  </script>
</body>
</html>"""

    html_path = out_path / f"{wing}_graph.html"
    html_path.write_text(html)
    console.print(f"[bold green]✓ HTML saved:[/bold green] {html_path}")
    console.print(f"  Open in browser: [dim]file://{html_path.resolve()}[/dim]")


# ---------------------------------------------------------------------------
# room  — list all papers, or enter one paper's room fully
# ---------------------------------------------------------------------------

@app.command()
def room(
    wing: str = typer.Argument(..., help="Wing name", autocompletion=_complete_wing),
    paper_id: Optional[str] = typer.Argument(None, help="arXiv paper ID (omit to list all rooms)"),
    hall: Optional[str] = typer.Option(
        None, "--hall", "-H",
        help=f"Show only one hall: {', '.join(HALLS)}",
        autocompletion=_complete_hall,
    ),
    full: bool = typer.Option(False, "--full", "-f", help="Print full drawer text (no truncation)"),
    linked_only: bool = typer.Option(False, "--linked", help="When listing: show only rooms with an Obsidian note"),
):
    """
    Without a paper ID: list all rooms in the wing.
    With a paper ID: enter that room and read its drawers.

    Example
    -------
      axiv research room diffusion-models                       # list all
      axiv research room diffusion-models --linked              # only linked
      axiv research room diffusion-models 2011.13456            # enter room
      axiv research room diffusion-models 2011.13456 --hall hall_facts
      axiv research room diffusion-models 2011.13456 --full
    """
    if paper_id is None:
        _list_rooms(wing, linked_only)
    else:
        _enter_room(wing, paper_id, hall, full)


def _list_rooms(wing: str, linked_only: bool) -> None:
    w = get_wing(wing, _palace_db())
    if not w:
        console.print(f"[red]Wing '{wing}' not found.[/red]")
        raise typer.Exit(1)

    all_rooms = list_rooms(wing, _palace_db())
    if linked_only:
        all_rooms = [r for r in all_rooms if r["note_path"]]

    if not all_rooms:
        msg = "No linked rooms yet." if linked_only else "No rooms yet."
        console.print(f"[yellow]{msg}[/yellow]")
        return

    console.print(f"\n[bold cyan]Rooms in wing:[/bold cyan] {wing}  ({len(all_rooms)} papers)\n")

    table = Table(
        "Paper ID", "Title", "Keywords", "Note", "Report",
        show_header=True, header_style="bold magenta",
        show_lines=True,
    )
    for r in all_rooms:
        kw = ", ".join(r["keywords"][:4]) if r["keywords"] else "—"
        note_str   = "[green]✓[/green]" if r["note_path"]   else "[dim]·[/dim]"
        report_str = "[green]✓[/green]" if r["report_path"] else "[dim]·[/dim]"
        table.add_row(r["paper_id"], r["title"], kw, note_str, report_str)
    console.print(table)
    console.print()


def _enter_room(wing: str, paper_id: str, hall: Optional[str], full: bool) -> None:
    data = get_room(wing, paper_id, _palace_db())
    if not data:
        console.print(f"[red]Room not found: {paper_id} in wing '{wing}'.[/red]")
        console.print(f"  Run `axiv research room {wing}` to list available papers.")
        raise typer.Exit(1)

    title    = data["title"]
    truncate = 0 if full else 600

    console.print(f"\n[bold cyan]Room:[/bold cyan] {paper_id}")
    console.print(f"[bold]{title}[/bold]\n")

    if data["summary"]:
        console.print(Panel(
            markup_escape(data["summary"]),
            title="[magenta]Closet (distilled summary)[/magenta]",
            border_style="magenta",
        ))

    if data["note_path"]:
        console.print(f"\n[bold green]Obsidian Note:[/bold green]  {data['note_path']}")
        if data["report_path"]:
            console.print(f"[bold green]Report:[/bold green]         {data['report_path']}")
        console.print(f"[dim]Linked: {data['linked_at']}[/dim]\n")
    else:
        console.print(
            "\n[yellow]No Obsidian note linked yet.[/yellow]  "
            f"Run `axiv research link {wing}` to generate notes in the background.\n"
        )

    from alphaxiv_cli.storage.palace import _HALL_DISPLAY
    halls_to_show = [hall] if hall else HALLS

    for h in halls_to_show:
        if h not in HALLS:
            console.print(f"[red]Unknown hall '{h}'[/red]")
            continue
        drawers = data["halls"].get(h, [])
        if not drawers:
            continue
        console.print(f"\n[bold magenta]{_HALL_DISPLAY[h]}[/bold magenta]")
        for d in drawers:
            raw = d["content"] if full else (
                d["content"][:truncate] + "…" if len(d["content"]) > truncate else d["content"]
            )
            console.print(Panel(markup_escape(raw), title=f"[dim]{markup_escape(d['label'])}[/dim]", border_style="dim"))

    if data["tunnels"]:
        console.print(f"\n[bold]Tunnels ({len(data['tunnels'])})[/bold]")
        for t in data["tunnels"]:
            arrow = f"[dim]{t['from_paper']}[/dim] —[{t['relation']}]→ [dim]{t['to_paper']}[/dim]"
            console.print(f"  {arrow}")
    console.print()


# ---------------------------------------------------------------------------
# link  — async Obsidian note generation for all wing papers
# ---------------------------------------------------------------------------

@app.command()
def link(
    wing: str = typer.Argument(..., help="Wing to link", autocompletion=_complete_wing),
    output_dir: Optional[str] = typer.Option(None, "--output", "-o", help="Obsidian notes directory (default: workspace notes_dir)"),
    limit: int = typer.Option(5, "--limit", "-l", help="Max similar papers per note"),
    relink: bool = typer.Option(False, "--relink", help="Regenerate notes even if already linked"),
    secret: Optional[str] = typer.Option(
        None, "--secret",
        help="Path to SECRET.md with alphaxiv credentials (default: SECRET.md in project root). "
             "Required for papers that don't have an AI overview yet — used to trigger generation via browser automation.",
    ),
    headless: bool = typer.Option(
        True, "--headless/--no-headless",
        help="Run the overview-generation browser in headless mode (default: headless).",
    ),
    background: bool = typer.Option(
        False, "--background", "-b",
        help="Fork to background and return immediately",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """
    Generate Obsidian notes for every paper in the wing and store the paths
    back in the palace so `room` and `synthesize` can point to them.

    Papers that already have an AI overview on alphaxiv are linked immediately.
    Papers without an overview are automatically queued for generation using
    browser automation (Playwright) with your alphaxiv credentials — the browser
    logs in, triggers generation, and polls until the overview is ready (up to
    90s per paper).

    Credentials are read from (in order):
      1. ALPHAXIV_EMAIL / ALPHAXIV_PASSWORD environment variables
      2. --secret path (default: SECRET.md in the project root)

    Example
    -------
      axiv research link point-source-inverse-problem
      axiv research link point-source-inverse-problem --no-headless   # visible browser
      axiv research link point-source-inverse-problem --background     # fire and forget
      axiv research link point-source-inverse-problem --relink         # regenerate all
    """
    w = get_wing(wing, _palace_db())
    if not w:
        console.print(f"[red]Wing '{wing}' not found.[/red]")
        raise typer.Exit(1)

    resolved_output = output_dir or str(_notes_dir())
    secret_path = Path(secret) if secret else (_ctx().root / "SECRET.md")

    if background:
        _fork_link(wing, resolved_output, limit, relink, str(secret_path), headless, verbose)
        return

    _run_link(wing, resolved_output, limit, relink, secret_path, headless, verbose)


def _fork_link(
    wing: str, output_dir: str, limit: int, relink: bool,
    secret: str, headless: bool, verbose: bool,
) -> None:
    """Fork link as a detached background process."""
    import subprocess, sys

    log_path = Path(output_dir) / "link.log"
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "alphaxiv_cli",
        "research", "link", wing,
        "--output", output_dir,
        "--limit", str(limit),
        "--secret", secret,
    ]
    if relink:
        cmd.append("--relink")
    if not headless:
        cmd.append("--no-headless")
    if verbose:
        cmd.append("--verbose")

    with open(log_path, "a") as log_fh:
        proc = subprocess.Popen(
            cmd,
            stdout=log_fh, stderr=log_fh,
            start_new_session=True,
            close_fds=True,
        )

    console.print(f"[bold green]✓ link started in background[/bold green]  PID={proc.pid}")
    console.print(f"  Tail progress: [dim]tail -f {log_path}[/dim]")
    console.print(f"  Check when done: [dim]axiv research room {wing} --linked[/dim]\n")


def _run_link(
    wing: str, output_dir: str, limit: int, relink: bool,
    secret_path: Path, headless: bool, verbose: bool,
) -> None:
    """Synchronous link: generate Obsidian notes for all wing papers.

    For papers that already have an AI overview: link immediately.
    For papers without an overview: trigger generation via Playwright
    (browser automation) using the credentials in secret_path, then link
    once the overview is ready.
    """
    from alphaxiv_cli.commands.graph import (
        build_note, get_arxiv_categories, sanitize_paper_id,
    )
    from alphaxiv_cli.overview_generator import (
        ensure_overview_generated, is_playwright_available,
    )
    from alphaxiv_cli.utils.helpers import extract_version_id

    out_path    = Path(output_dir)
    reports_dir = out_path / "reports"
    images_dir  = out_path / "images"
    out_path.mkdir(parents=True, exist_ok=True)

    today          = _today()
    existing_links = get_all_note_links(wing, _palace_db()) if not relink else {}
    all_rooms_list = list_rooms(wing, _palace_db())
    to_link = [
        r for r in all_rooms_list
        if relink or r["paper_id"] not in existing_links
    ]

    has_playwright = is_playwright_available()
    secret_exists  = secret_path.exists()

    console.print(f"\n[bold cyan]Linking wing:[/bold cyan] {wing}")
    console.print(f"  {len(all_rooms_list)} rooms total, {len(to_link)} to generate")
    if not has_playwright:
        console.print(f"  [yellow]Playwright not installed — papers without overviews will be skipped.[/yellow]")
        console.print(f"  [dim]pip install playwright && playwright install chromium[/dim]")
    elif not secret_exists:
        console.print(
            f"  [yellow]No credentials found at {secret_path} — "
            f"papers without overviews will be skipped.[/yellow]"
        )
        console.print(f"  [dim]Create SECRET.md or set ALPHAXIV_EMAIL / ALPHAXIV_PASSWORD[/dim]")
    else:
        console.print(f"  [dim]Credentials: {secret_path}  |  headless: {headless}[/dim]")
    console.print()

    linked = skipped = generated = 0

    with AlphaXivClient() as client:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Generating notes…", total=len(to_link))

            for r in to_link:
                pid = r["paper_id"]
                try:
                    info = client.resolve_paper(pid)
                    if not info:
                        skipped += 1
                        progress.advance(task)
                        continue

                    version_id = extract_version_id(info)
                    overview = None

                    # --- try to get existing overview ---
                    if version_id:
                        try:
                            overview = client.get_overview(version_id)
                        except AlphaXivError:
                            pass

                    # --- no overview: trigger generation via Playwright ---
                    if (not overview or not overview.get("overview")) and version_id:
                        if has_playwright and (secret_exists or _has_env_creds()):
                            # Stop the live progress display before launching browser
                            progress.stop()
                            console.print(
                                f"\n  [yellow]⟳[/yellow] {pid} — no overview yet, "
                                f"requesting generation via browser…"
                            )
                            ok = ensure_overview_generated(
                                pid, version_id, client,
                                secret_file=secret_path if secret_exists else None,
                                headless=headless,
                            )
                            progress.start()
                            if ok:
                                try:
                                    overview = client.get_overview(version_id)
                                    generated += 1
                                except AlphaXivError:
                                    pass

                    # --- still no overview: skip ---
                    if not overview or not overview.get("overview"):
                        if verbose:
                            console.print(f"  [dim]skip {pid} — overview unavailable[/dim]")
                        skipped += 1
                        progress.advance(task)
                        continue

                    # --- build and write note ---
                    similar = client.get_similar_papers(pid, limit)
                    cats    = get_arxiv_categories(pid)
                    note_md, report_md = build_note(
                        pid, info, overview, similar, today,
                        {}, images_dir, False, cats,
                    )

                    safe_id   = sanitize_paper_id(pid)
                    note_path = out_path / f"{safe_id}.md"
                    note_path.write_text(note_md)

                    report_path = None
                    if report_md:
                        reports_dir.mkdir(parents=True, exist_ok=True)
                        report_path = reports_dir / f"{safe_id}_report.md"
                        report_path.write_text(report_md)

                    set_note_link(
                        wing, pid,
                        note_path.resolve(),
                        report_path.resolve() if report_path else None,
                        _palace_db(),
                    )
                    linked += 1

                    if verbose:
                        console.print(
                            f"  [green]✓[/green] {pid}: {info.get('title','')[:55]}"
                        )
                    progress.update(task, description=f"[green]✓ {pid}")

                except Exception as e:
                    logger.warning(f"link failed for {pid}: {e}")
                    skipped += 1

                progress.advance(task)

    console.print(
        f"\n[bold green]✓ Linked {linked}/{len(to_link)}[/bold green]"
        + (f"  [yellow](generated {generated} new overview(s))[/yellow]" if generated else "")
        + (f"  [dim](skipped {skipped})[/dim]" if skipped else "")
    )
    console.print(f"  View: [dim]axiv research room {wing} --linked[/dim]\n")


def _has_env_creds() -> bool:
    """Return True if ALPHAXIV_EMAIL / ALPHAXIV_PASSWORD are set in the environment."""
    import os
    return bool(os.getenv("ALPHAXIV_EMAIL") and os.getenv("ALPHAXIV_PASSWORD"))


# ---------------------------------------------------------------------------
# wings
# ---------------------------------------------------------------------------

@app.command()
def wings():
    """List all research wings in the palace."""
    _print_palace_status(list_wings(_palace_db()))
