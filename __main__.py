#!/usr/bin/env python3
"""AlphaXiv CLI - Main entry point."""
import typer
import json
import sys
from typing import Optional
from pathlib import Path
from rich.console import Console
from rich.tree import Tree

from alphaxiv_cli.client import AlphaXivClient, AlphaXivError
from alphaxiv_cli.commands import get_cmd, similar_cmd, explore_cmd, graph_cmd, research_cmd

app = typer.Typer(
    name="axiv",
    help="AlphaXiv CLI - Interact with alphaXiv API and explore paper connections"
)

app.add_typer(get_cmd.app, name="get")
app.add_typer(similar_cmd.app, name="similar")
app.add_typer(explore_cmd.app, name="explore")
app.add_typer(graph_cmd.app, name="graph")
app.add_typer(research_cmd.app, name="research")

_console = Console()


@app.command()
def init(
    directory: Optional[Path] = typer.Argument(
        None,
        help="Directory to initialise (default: current directory)",
    ),
    notes_dir: Optional[str] = typer.Option(
        None, "--notes", help="Where to write Obsidian notes (absolute or relative to project root)"
    ),
    reports_dir: Optional[str] = typer.Option(
        None, "--reports", help="Where to write report notes"
    ),
    force: bool = typer.Option(False, "--force", help="Reinitialise even if .axiv already exists"),
):
    """
    Initialise a local research workspace in the given directory.

    Creates a .axiv marker file that tells every axiv command to store its
    palace database, ChromaDB vectors, notes, and cache inside this directory
    instead of the global ~/.alphaxiv fallback.

    Once initialised, any axiv command run from inside this directory tree
    will automatically use the local workspace — no extra flags needed.

    Example
    -------
      cd ~/research/diffusion-papers
      axiv init                          # init in CWD
      axiv init ~/research/llm-papers    # init elsewhere
      axiv init --notes ~/obsidian/papers  # custom notes location
      axiv init                          # show current workspace if already init'd
    """
    from alphaxiv_cli.context import init_project, get_context

    target = Path(directory) if directory else Path.cwd()

    try:
        ctx = init_project(target, notes_dir=notes_dir, reports_dir=reports_dir, force=force)
    except FileExistsError as e:
        # Already initialised — just show current context
        ctx = get_context(target)
        _console.print(f"[yellow]Already initialised.[/yellow] Showing current workspace:\n")
        _print_context(ctx)
        return

    _console.print(f"\n[bold green]✓ Initialised workspace[/bold green]\n")
    _print_context(ctx)


@app.command()
def where():
    """
    Show which workspace (local or global) the current directory resolves to,
    and where each path lives.

    Example
    -------
      cd ~/research/diffusion-papers
      axiv where
    """
    from alphaxiv_cli.context import get_context
    ctx = get_context()
    _print_context(ctx)


def _print_context(ctx) -> None:
    scope = "[cyan]local[/cyan]" if ctx.is_local else "[dim]global (fallback)[/dim]"
    _console.print(f"[bold]Workspace:[/bold] {scope}  {ctx.root}\n")

    tree = Tree(f"[bold]{ctx.root}[/bold]")
    tree.add(f"[dim].axiv[/dim]                  marker file")
    tree.add(f"[green]palace.sqlite3[/green]         {ctx.palace_db}")
    tree.add(f"[green]palace/[/green]                {ctx.palace_dir}")
    tree.add(f"[green]knowledge_graph.sqlite3[/green] {ctx.kg_db}")
    tree.add(f"[green]notes/[/green]                 {ctx.notes_dir}")
    tree.add(f"[green]reports/[/green]               {ctx.reports_dir}")
    tree.add(f"[green]cache/[/green]                 {ctx.cache_dir}")
    _console.print(tree)
    _console.print()


@app.command()
def search(
    query: str = typer.Argument(..., help=(
        "Search query. Plain text searches title+abstract. "
        "Prefix with ti: (title), au: (author), cat: (category e.g. cs.LG). "
        "Combine with AND/OR: 'ti:diffusion AND cat:cs.LG'"
    )),
    limit: int = typer.Option(10, "--limit", "-n", help="Max results"),
    sort: str = typer.Option(
        "relevance", "--sort", "-s",
        help="Sort by: relevance | lastUpdatedDate | submittedDate",
    ),
    cat_filter: Optional[str] = typer.Option(
        None, "--cat",
        help=(
            "Post-filter: keep only papers where this category appears anywhere "
            "in their category list (primary or cross-listed). "
            "Useful because arXiv's cat: query matches cross-listings, so primary "
            "category shown may differ from the one you filtered on."
        ),
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
):
    """
    Search arXiv papers by keyword, title, author, or category.

    Note on cat: queries
    --------------------
    arXiv matches cat: against ALL categories a paper belongs to, including
    cross-listings.  A result with primary=math.MG may still appear for
    cat:math.AP because it is cross-listed there.  The Categories column
    shows the full list so you can see why each result matched.
    Use --cat math.AP to post-filter and keep only strict matches.

    Example
    -------
      axiv search "score matching generative models"
      axiv search "ti:consistency models" --limit 5
      axiv search "au:song AND cat:cs.LG" --sort lastUpdatedDate
      axiv search "cat:math.AP" --cat math.AP        # strict primary+cross filter
      axiv search "diffusion" --json | jq '.[].paper_id'
    """
    from rich.table import Table

    # Fetch more when post-filtering so we still get `limit` results after drop
    fetch_limit = limit * 3 if cat_filter else limit

    client = AlphaXivClient()
    try:
        results = client.search(query, limit=fetch_limit, sort_by=sort)
    except AlphaXivError as e:
        _console.print(f"[red]Error:[/red] {e}", file=sys.stderr)
        raise typer.Exit(1)
    finally:
        client.close()

    # Post-filter by category (any position in categories list)
    if cat_filter:
        cat_lower = cat_filter.lower()
        results = [
            r for r in results
            if any(c.lower() == cat_lower for c in r.get("categories", []))
        ][:limit]

    if json_output:
        print(json.dumps(results, indent=2))
        return

    if not results:
        msg = f"No results"
        if cat_filter:
            msg += f" with category {cat_filter}"
        _console.print(f"[yellow]{msg}.[/yellow]")
        return

    header = f"\n[bold cyan]arXiv search:[/bold cyan] \"{query}\""
    if cat_filter:
        header += f"  [dim]--cat {cat_filter}[/dim]"
    header += f"  [dim]({len(results)} result{'s' if len(results) != 1 else ''})[/dim]\n"
    _console.print(header)

    table = Table(show_header=True, header_style="bold magenta", show_lines=True)
    table.add_column("#",          width=3,  justify="right")
    table.add_column("ID",         no_wrap=True)
    table.add_column("Title",      no_wrap=False)
    table.add_column("Authors",    no_wrap=False)
    table.add_column("Categories", no_wrap=False)
    table.add_column("Date",       no_wrap=True, width=11)

    for i, paper in enumerate(results, 1):
        pid      = paper.get("paper_id", "?")
        title    = paper.get("title", "")
        authors  = paper.get("authors", [])
        cats     = paper.get("categories", [])
        date     = paper.get("updated") or paper.get("published", "")
        first_au = authors[0] if authors else "—"
        au_str   = first_au + (f" +{len(authors)-1}" if len(authors) > 1 else "")

        if cat_filter:
            cat_strs = [
                f"[bold]{c}[/bold]" if c.lower() == cat_filter.lower() else f"[dim]{c}[/dim]"
                for c in cats
            ]
        else:
            cat_strs = [cats[0]] + [f"[dim]{c}[/dim]" for c in cats[1:]] if cats else []
        cat_str = " ".join(cat_strs)

        table.add_row(str(i), pid, title, au_str, cat_str, date)

    _console.print(table)

    # Interactive checkbox → start research wing
    _interactive_start(results)


def _interactive_start(results: list) -> None:
    """
    After showing search results:
      1. Checkbox — select papers
      2. Show proposed label + slug extracted from selected titles
      3. Let user edit both interactively
      4. Ingest selected papers into a new (or existing) wing

    Silently skips when stdout is not a TTY (e.g. piped to jq).
    """
    import re
    if not sys.stdout.isatty():
        return

    try:
        import questionary
    except ImportError:
        _console.print(
            "\n[dim]Tip: pip install questionary for interactive paper selection.[/dim]\n"
        )
        return

    from alphaxiv_cli.utils.naming import extract_wing_names, slug_from_label
    from alphaxiv_cli.commands.research import _ingest_paper, add_tunnel, _palace_db
    from alphaxiv_cli.storage.palace import create_wing as _create_wing
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

    # ── 1. Checkbox selection ──────────────────────────────────────────────
    SELECT_ALL_SENTINEL = "__SELECT_ALL__"
    choices = [
        questionary.Choice(
            title=">> Select all papers <<",
            value=SELECT_ALL_SENTINEL,
        ),
    ] + [
        questionary.Choice(
            title=f"[{p['paper_id']}]  {p['title'][:70]}",
            value=p,
        )
        for p in results
    ]

    _console.print()
    raw_selected = questionary.checkbox(
        "Select papers to add to a research wing:",
        choices=choices,
        instruction="(Space=toggle  a=select-all  Enter=confirm  Ctrl-C=cancel)",
    ).ask()

    if not raw_selected:
        _console.print("[dim]No papers selected.[/dim]\n")
        return

    # If "Select all" was toggled, replace with every paper
    if SELECT_ALL_SENTINEL in raw_selected:
        selected = list(results)
    else:
        selected = [p for p in raw_selected if p != SELECT_ALL_SENTINEL]

    if not selected:
        _console.print("[dim]No papers selected.[/dim]\n")
        return

    # ── 2. Extract proposed names ──────────────────────────────────────────
    titles    = [p["title"]          for p in selected]
    abstracts = [p.get("abstract", "") for p in selected]
    slug, label = extract_wing_names(titles, abstracts)

    _console.print(f"\n[bold]Suggested wing names[/bold] (from {len(selected)} selected paper(s)):\n")
    _console.print(f"  [bold]Label[/bold]  (long, human-readable)  →  {label}")
    _console.print(f"  [bold]Slug[/bold]   (short, CLI argument)   →  [cyan]{slug}[/cyan]\n")

    # ── 3. Edit label ──────────────────────────────────────────────────────
    final_label = questionary.text(
        "Wing label — edit or press Enter to accept:",
        default=label,
    ).ask()
    if final_label is None:          # Ctrl-C
        _console.print("[dim]Cancelled.[/dim]\n")
        return
    final_label = final_label.strip() or label

    # Re-derive slug if label was changed, else keep the extracted one
    proposed_slug = slug_from_label(final_label) if final_label != label else slug

    # ── 4. Edit slug ───────────────────────────────────────────────────────
    final_slug = questionary.text(
        "Wing slug — edit or press Enter to accept:",
        default=proposed_slug,
        validate=lambda s: (
            True if re.match(r"^[a-zA-Z0-9][a-zA-Z0-9\-]*$", s.strip())
            else "Slug must start with a letter/digit and contain only letters, digits, hyphens"
        ),
    ).ask()
    if final_slug is None:
        _console.print("[dim]Cancelled.[/dim]\n")
        return
    final_slug = final_slug.strip()

    # ── 5. Confirm ─────────────────────────────────────────────────────────
    paper_ids = [p["paper_id"] for p in selected]
    _console.print(
        f"\n  Wing  : [cyan]{final_slug}[/cyan]\n"
        f"  Label : {final_label}\n"
        f"  Papers: {', '.join(paper_ids)}\n"
    )
    confirmed = questionary.confirm("Start this wing?", default=True).ask()
    if not confirmed:
        _console.print("[dim]Cancelled.[/dim]\n")
        return

    # ── 6. Ingest ──────────────────────────────────────────────────────────
    _console.print(
        f"\n[bold cyan]Starting wing:[/bold cyan] {final_slug}  "
        f"[dim]({len(selected)} paper(s))[/dim]\n"
    )

    _create_wing(final_slug, final_label, _palace_db())

    ok = 0
    seed_set = set(paper_ids)
    with AlphaXivClient() as client:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=_console,
        ) as progress:
            task = progress.add_task("Ingesting…", total=len(paper_ids))
            for pid in paper_ids:
                if _ingest_paper(client, final_slug, pid, verbose=True):
                    ok += 1
                    try:
                        similar = client.get_similar_papers(pid, limit=20)
                        for sp in similar:
                            spid = sp.get("universal_paper_id") or sp.get("paper_id")
                            if spid and spid in seed_set and spid != pid:
                                add_tunnel(
                                    final_slug, pid, final_slug, spid,
                                    "similar", _palace_db(),
                                )
                    except AlphaXivError:
                        pass
                progress.advance(task)

    _console.print(
        f"\n[bold green]✓ {ok}/{len(paper_ids)} papers added to "
        f"wing '[cyan]{final_slug}[/cyan]'[/bold green]\n"
    )
    _console.print(f"  axiv research room     {final_slug}")
    _console.print(f"  axiv research expand   {final_slug}")
    _console.print(f"  axiv research visualize {final_slug}\n")


@app.command()
def login():
    """
    Save an alphaxiv.org login session for browser automation.

    Opens a visible Chromium browser at alphaxiv.org/signin.
    Log in normally (Google OAuth, 2FA — whatever the site requires).
    The session is saved to the workspace browser profile automatically
    once login is detected.  Future `axiv research link` runs reuse
    this session headlessly — you never need to log in again unless
    the session expires.

    Example
    -------
      axiv login          # run once per machine / workspace
      axiv research link point-source-inverse-problem
    """
    from alphaxiv_cli.overview_generator import interactive_login, is_playwright_available
    from alphaxiv_cli.context import get_context

    if not is_playwright_available():
        _console.print("[red]Playwright is not installed.[/red]")
        _console.print("  pip install playwright && playwright install chromium")
        raise typer.Exit(1)

    ctx = get_context()
    _console.print(f"\n[bold cyan]alphaxiv login[/bold cyan]")
    _console.print(f"[dim]Browser profile: {ctx.root / 'browser-profile'}[/dim]\n")

    ok = interactive_login()
    if ok:
        _console.print(f"\n[bold green]✓ Session saved.[/bold green]")
        _console.print(f"  Run `axiv research link <wing>` to generate overviews.\n")
    else:
        _console.print(f"\n[red]Login was not completed.[/red]")
        _console.print(f"  Try again with `axiv login`.\n")
        raise typer.Exit(1)


@app.command()
def version():
    """Show version."""
    from alphaxiv_cli import __version__
    print(f"alphaxiv-cli {__version__}")


if __name__ == "__main__":
    app()
