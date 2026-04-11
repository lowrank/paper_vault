# AlphaXiv CLI -- Usage Guide

> **Version:** 0.1.0
> **Entry point:** `axiv`

## Table of Contents

1. [Installation & Setup](#installation--setup)
2. [The Memory Palace Metaphor](#the-memory-palace-metaphor)
3. [Typical Workflow](#typical-workflow)
4. [Commands Reference](#commands-reference)
   - [Workspace](#workspace-commands)
   - [Search](#search)
   - [Get (Paper Data)](#get-paper-data)
   - [Similar](#similar-papers)
   - [Explore](#explore)
   - [Graph](#graph-obsidian-knowledge-graph)
   - [Research](#research-commands)
   - [Login](#login)
   - [Version](#version)
5. [Authentication](#authentication)
6. [Configuration & Files](#configuration--files)
7. [Test Results](#test-results)

---

## Installation & Setup

```bash
# Clone and install in editable mode
pip install -e .

# Verify
axiv version
```

**Dependencies note:** This project requires `click==8.1.7` with `typer==0.15.1`.
Click 8.3+ breaks Typer with a `TyperArgument.make_metavar()` error.

### Initialize a workspace

```bash
# Create a local workspace in the current directory
axiv init

# Force-reinitialise (wipe existing workspace data)
axiv init --force

# Check which workspace you're in
axiv where
```

A workspace is identified by a `.axiv` marker file. The CLI walks up from CWD
to find it. If none is found, it falls back to `~/.alphaxiv/` (the global
workspace).

You can also override the workspace with the `AXIV_WORKSPACE` environment variable:

```bash
AXIV_WORKSPACE=/path/to/workspace axiv research wings
```

---

## The Memory Palace Metaphor

The research workflow is organized around a **Memory Palace** -- a structured
metaphor for storing and navigating research knowledge:

| Concept     | Meaning                                                    |
|-------------|-----------------------------------------------------------|
| **Palace**  | Your entire research workspace (one SQLite database)       |
| **Wing**    | A research topic (e.g., "score-matching", "diffusion-models"). Each wing holds a collection of related papers. |
| **Hall**    | A thematic category within a wing. There are 5 predefined halls: |
|             | - `hall_facts` -- Established Facts & Results              |
|             | - `hall_discoveries` -- Discoveries & Insights             |
|             | - `hall_questions` -- Open Questions & Gaps                |
|             | - `hall_methods` -- Methods & Architectures                |
|             | - `hall_context` -- Background & Related Work              |
| **Room**    | A paper within a hall. Each paper gets a room in every hall it has content for. |
| **Drawer**  | A piece of extracted knowledge (a paragraph/fact) stored in a room. |
| **Closet**  | A summary of the paper (AI overview, abstract, key topics). |
| **Tunnel**  | A cross-reference between two papers (citation, similarity link). |

When you ingest a paper, its content is split into drawers and filed into the
appropriate halls. When you query, the system searches across drawers using
vector embeddings (ChromaDB).

---

## Typical Workflow

Here is the recommended end-to-end research workflow:

### 1. Search for papers

```bash
axiv search "score matching generative models" -n 10
axiv search "ti:consistency models" --limit 5
axiv search "au:song AND cat:cs.LG" --sort lastUpdatedDate
```

The search command shows an interactive paper selection UI. Use arrow keys and
space to select papers. The first option is **Select All**.

### 2. Create a wing with seed papers

```bash
axiv research start score-matching 2011.13456 2206.00364 \
  --topic "Score-based generative models" -v
```

This creates a wing named `score-matching`, fetches each paper's info and AI
overview from alphaxiv, extracts knowledge into halls/drawers, and stores
embeddings in ChromaDB.

### 3. Expand the wing (BFS)

```bash
axiv research expand score-matching --limit 3 --hops 2
```

Follows "similar paper" links for each paper already in the wing, ingesting
new papers up to `--limit` per paper, repeated for `--hops` rounds.

### 4. (Optional) Generate AI overviews

If some papers don't have AI overviews on alphaxiv.org yet:

```bash
# One-time login (saves browser session)
axiv login

# Trigger overview generation for all papers in the wing
axiv research start score-matching 2011.13456 -g
# or during link phase:
axiv research link score-matching
```

Overview generation uses Playwright browser automation. It triggers the
"Generate" button on alphaxiv.org for each paper (5-second delay between papers
to avoid rate limits), then polls in the background until all overviews are
ready.

### 5. Query the wing

```bash
# Semantic search across all papers in the wing
axiv research query score-matching "how does noise scheduling affect generation quality?"

# Walk through a specific hall
axiv research walk score-matching --hall hall_methods

# Inspect a specific paper's room
axiv research room score-matching 2011.13456 --hall hall_context

# List all papers in the wing
axiv research room score-matching
```

### 6. Generate Obsidian notes (link)

```bash
axiv research link score-matching -v
```

Creates Obsidian-compatible Markdown notes for each paper, with cross-references
to similar papers and a structured layout.

### 7. Trim the wing

After expanding, you may have papers that aren't closely related. Trim removes
outliers based on embedding similarity:

```bash
# Preview what would be removed (keep top 10)
axiv research trim score-matching --keep 10 --dry-run

# Remove papers below a similarity threshold
axiv research trim score-matching --threshold 0.4

# Interactive mode -- shows ranking, lets you pick
axiv research trim score-matching
```

### 8. Synthesize

```bash
axiv research synthesize score-matching --output synthesis.md
```

Generates a structured Markdown synthesis document that bridges all papers in
the wing, organized by hall.

### 9. Visualize

```bash
axiv research visualize score-matching
```

Outputs an interactive HTML graph and a PNG image showing the paper network
(papers as nodes, tunnels/citations as edges).

### 10. Review wing status

```bash
# See the palace tree structure
axiv research status score-matching

# List all wings
axiv research wings
```

---

## Commands Reference

### Workspace Commands

#### `axiv init`

Initialize a local research workspace.

```
axiv init [--force]
```

| Option    | Description                        |
|-----------|------------------------------------|
| `--force` | Re-initialize, wiping existing data |

#### `axiv where`

Show which workspace the current directory resolves to.

```
axiv where
```

---

### Search

#### `axiv search`

Search arXiv papers by keyword, title, author, or category.

```
axiv search QUERY [OPTIONS]
```

| Option          | Default     | Description                                              |
|-----------------|-------------|----------------------------------------------------------|
| `-n, --limit`   | 10          | Max results                                              |
| `-s, --sort`    | `relevance` | Sort by: `relevance`, `lastUpdatedDate`, `submittedDate` |
| `--cat`         | None        | Post-filter by category (e.g. `cs.LG`, `math.AP`)       |
| `-j, --json`    | off         | JSON output                                              |

**Query syntax:**
- Plain text: searches title + abstract
- `ti:` prefix: title search (e.g. `ti:diffusion`)
- `au:` prefix: author search (e.g. `au:song`)
- `cat:` prefix: category search (e.g. `cat:cs.LG`)
- Combine with `AND`/`OR`: `ti:diffusion AND cat:cs.LG`

**Examples:**

```bash
axiv search "score matching generative models"
axiv search "ti:consistency models" --limit 5
axiv search "au:song AND cat:cs.LG" --sort lastUpdatedDate
axiv search "cat:math.AP" --cat math.AP        # strict category filter
axiv search "diffusion" --json | jq '.[].paper_id'
```

---

### Get (Paper Data)

#### `axiv get info`

Get basic paper metadata (title, authors, abstract, categories).

```bash
axiv get info 2206.00364
```

#### `axiv get overview`

Get the AI-generated overview (summary) from alphaxiv.org.

```bash
axiv get overview 2206.00364
```

#### `axiv get metrics`

Get paper metrics (citations, views, etc.).

```bash
axiv get metrics 2206.00364
```

Note: Metrics are not available for all papers (may return 404).

#### `axiv get fulltext`

Get paper full text (extracted from PDF).

```bash
axiv get fulltext 2206.00364
```

Note: Full text is not available for all papers (may return 404).

#### `axiv get all`

Fetch all available data for a paper (info + overview + metrics + resources).

```bash
axiv get all 2206.00364
```

#### `axiv get status`

Check the overview generation status for a paper.

```bash
axiv get status 2206.00364
```

---

### Similar Papers

#### `axiv similar main`

Get similar papers for a given arXiv ID, optionally traversing BFS.

```
axiv similar main PAPER_ID [OPTIONS]
```

| Option        | Default | Description                      |
|---------------|---------|----------------------------------|
| `-n, --limit` | 5       | Max similar papers per paper     |
| `-d, --depth` | 1       | BFS depth                        |
| `-j, --json`  | off     | JSON output                      |
| `-v, --verbose`| off    | Verbose output                   |

```bash
axiv similar main 2011.13456
axiv similar main 2011.13456 -d 2 -n 3 --json
```

Note: The similar-papers API returns 404 for some papers.

---

### Explore

#### `axiv explore main`

Explore paper connections deeply (similar + similar-of-similar).

```
axiv explore main PAPER_ID [OPTIONS]
```

| Option          | Default  | Description                    |
|-----------------|----------|--------------------------------|
| `-d, --depth`   | 3        | Exploration depth (1-5)        |
| `-n, --limit`   | 5        | Similar papers per paper       |
| `-j, --json`    | off      | JSON output                    |
| `-o, --output`  | None     | Save to file                   |
| `-v, --verbose`  | off     | Verbose output                 |

```bash
axiv explore main 2011.13456 -d 2 -n 3 -v
```

---

### Graph (Obsidian Knowledge Graph)

#### `axiv graph main`

Build Obsidian notes with BFS paper connections. Creates Markdown notes with
cross-references for use in Obsidian.

```
axiv graph main PAPER_ID [OPTIONS]
```

| Option                     | Default  | Description                             |
|----------------------------|----------|-----------------------------------------|
| `-o, --output`             | `output` | Output directory                        |
| `-n, --iterations`         | 3        | BFS iterations                          |
| `-l, --limit`              | 5        | Similar papers per paper                |
| `-v, --verbose`            | off      | Verbose output                          |
| `--images`                 | off      | Download images from overview           |
| `--headless/--no-headless` | headless | Browser visibility for overview generation |

```bash
axiv graph main 2011.13456 -n 2 -l 3 -v
```

---

### Research Commands

The `axiv research` subcommand group is the primary structured workflow.

#### `axiv research start`

Begin (or resume) a research session for a topic.

```
axiv research start WING PAPER_IDS... [OPTIONS]
```

| Option                      | Default  | Description                                  |
|-----------------------------|----------|----------------------------------------------|
| `-t, --topic`               | None     | Human-readable topic description             |
| `-g, --generate-overviews`  | off      | Trigger AI overview generation for all papers |
| `--secret`                  | None     | Path to SECRET.md with credentials           |
| `--headless/--no-headless`  | headless | Browser visibility                           |
| `-v, --verbose`             | off      | Verbose output                               |

```bash
axiv research start score-matching 2011.13456 2206.00364 \
  --topic "Score-based generative models" -v

# With overview generation
axiv research start score-matching 2011.13456 2206.00364 -g
```

#### `axiv research expand`

BFS-expand a wing by following similar-paper links.

```
axiv research expand WING [OPTIONS]
```

| Option          | Default | Description                  |
|-----------------|---------|------------------------------|
| `-l, --limit`   | 5       | Similar papers per paper     |
| `--hops`        | 1       | BFS hops                     |
| `-v, --verbose`  | off    | Verbose output               |

```bash
axiv research expand score-matching --limit 3 --hops 2
```

#### `axiv research query`

Semantic search inside a wing (or across all wings).

```
axiv research query WING QUESTION [OPTIONS]
```

| Option          | Default | Description              |
|-----------------|---------|--------------------------|
| `-n, --limit`   | 5       | Max results              |
| `--hall`        | None    | Restrict to a specific hall |

```bash
axiv research query score-matching "how does noise affect generation?"
axiv research query score-matching "methods" --hall hall_methods
```

#### `axiv research walk`

Walk through a hall and read the drawers.

```
axiv research walk WING [OPTIONS]
```

| Option    | Default | Description                                  |
|-----------|---------|----------------------------------------------|
| `--hall`  | None    | Which hall to walk (e.g. `hall_facts`, `hall_methods`) |

```bash
axiv research walk score-matching --hall hall_facts
axiv research walk score-matching --hall hall_context
```

#### `axiv research room`

List rooms or inspect a specific paper's room.

```
axiv research room WING [PAPER_ID] [OPTIONS]
```

- Without `PAPER_ID`: lists all rooms (papers) in the wing.
- With `PAPER_ID`: shows the drawers for that paper.

| Option     | Default | Description                  |
|------------|---------|------------------------------|
| `--hall`   | None    | Restrict to a specific hall  |
| `--linked` | off     | Show only linked papers      |

```bash
# List all papers in the wing
axiv research room score-matching

# Read a specific paper's drawers
axiv research room score-matching 2011.13456 --hall hall_context
```

#### `axiv research link`

Generate Obsidian notes for every paper in the wing.

```
axiv research link WING [OPTIONS]
```

| Option                     | Default  | Description                                     |
|----------------------------|----------|-------------------------------------------------|
| `-o, --output`             | None     | Obsidian notes directory (default: workspace)   |
| `-l, --limit`              | 5        | Max similar papers per note                     |
| `--relink`                 | off      | Regenerate notes even if already linked         |
| `--secret`                 | None     | Path to SECRET.md with credentials              |
| `--headless/--no-headless` | headless | Browser visibility                              |
| `-b, --background`         | off      | Fork to background and return immediately       |
| `-v, --verbose`            | off      | Verbose output                                  |

```bash
axiv research link score-matching -v
axiv research link score-matching --no-headless  # visible browser
axiv research link score-matching --relink       # regenerate all notes
```

#### `axiv research trim`

Trim a wing by removing the least-related papers based on embedding similarity.

```
axiv research trim WING [OPTIONS]
```

| Option            | Default | Description                                       |
|-------------------|---------|---------------------------------------------------|
| `-k, --keep`      | 0       | Keep top N papers (0 = interactive)               |
| `-t, --threshold`  | 0.0     | Remove papers below this avg similarity (0-1)     |
| `-n, --dry-run`    | off     | Show what would be removed without deleting       |
| `-y, --yes`        | off     | Skip confirmation prompt                          |
| `-v, --verbose`    | off     | Verbose output                                    |

**Three modes:**
1. `--keep N` -- Keep the top N most-related papers, remove the rest.
2. `--threshold T` -- Remove papers whose average similarity < T.
3. Neither -- Interactive mode: shows a ranking table and lets you pick papers to remove.

```bash
# Preview: keep top 10 papers
axiv research trim diffusion-models --keep 10 --dry-run

# Remove papers below similarity threshold
axiv research trim diffusion-models --threshold 0.4

# Interactive mode
axiv research trim diffusion-models

# Auto-confirm removal
axiv research trim diffusion-models --keep 5 --yes
```

#### `axiv research synthesize`

Generate a structured synthesis Markdown document from all papers in the wing.

```
axiv research synthesize WING [OPTIONS]
```

| Option        | Default | Description                   |
|---------------|---------|-------------------------------|
| `-o, --output` | None   | Save synthesis to this file   |

```bash
axiv research synthesize score-matching --output synthesis.md
```

#### `axiv research visualize`

Render the paper graph as an interactive HTML file and PNG.

```
axiv research visualize WING [OPTIONS]
```

| Option          | Default         | Description          |
|-----------------|-----------------|----------------------|
| `-o, --output`  | `output/`       | Output directory     |
| `--format`      | `html`          | Output format        |

```bash
axiv research visualize score-matching
# Opens: output/score-matching_graph.html
```

#### `axiv research status`

Print a structured overview of a specific wing (tree view with halls, rooms,
tunnels, synthesis count, closet summaries).

```bash
axiv research status score-matching
```

#### `axiv research wings`

List all research wings in the palace.

```bash
axiv research wings
```

---

### Login

#### `axiv login`

Save an alphaxiv.org login session for browser automation.

Opens a visible Chromium browser at alphaxiv.org/signin. Log in normally
(Google OAuth, 2FA, etc.). The session is saved to the workspace browser
profile automatically. Future `link` and `start -g` runs reuse this session
headlessly.

```bash
axiv login  # run once per machine/workspace
```

---

### Version

```bash
axiv version
```

---

## Authentication

Some features (AI overview generation via `link` and `start -g`) require
an authenticated alphaxiv.org session. Authentication is attempted in the
following order:

### 1. Saved browser session (recommended)

```bash
axiv login  # run once per machine/workspace
```

Opens a visible Chromium browser at alphaxiv.org/signin. Log in manually
(Google OAuth, 2FA, etc.). The session is saved to a persistent browser
profile and reused headlessly for all future `link` and `start -g` runs.

This is the **recommended** method, especially for Google OAuth accounts
(which cannot log in programmatically because Google blocks headless logins).

### 2. Credential-based login (for password accounts)

If no saved session exists, the CLI will attempt programmatic login using
email/password credentials. This works for alphaxiv accounts that have
password authentication enabled. Google-only accounts must use `axiv login`.

**From environment variables:**

```bash
export ALPHAXIV_EMAIL="your@email.com"
export ALPHAXIV_PASSWORD="your-password"
```

**From SECRET.md file:**

Create a `SECRET.md` file in your workspace root (or specify with `--secret`):

```markdown
email: your@email.com
password: your-password
```

The file should have restricted permissions (`chmod 600 SECRET.md`).

### 3. No authentication

If neither a saved session nor credentials are available, overview generation
is skipped. Papers without existing AI overviews on alphaxiv.org will be
skipped during `link` and `start -g`.

### Authentication flow summary

```
axiv research link wing -v
  1. Check saved browser session (from `axiv login`)
  2. If no session: attempt credential login (SECRET.md / env vars)
  3. If credential login fails: skip overview generation
```

For Google-linked accounts (the most common case), run `axiv login` once.
The session typically lasts weeks to months.

---

## Configuration & Files

### Workspace structure

```
your-project/
  .axiv                       # Workspace marker file
  palace.sqlite3              # SQLite database (wings, rooms, drawers, etc.)
  knowledge_graph.sqlite3     # Knowledge graph database
  .cache/                     # HTTP request cache
  palace/
    chroma.sqlite3            # ChromaDB vector store
  output/                     # Generated visualizations
  notes/                      # Generated Obsidian notes (from link)
```

### Global workspace

If no `.axiv` marker is found walking up from CWD, the CLI falls back to:

```
~/.alphaxiv/
```

### Key constants (config.py)

| Constant                | Default Value                               |
|------------------------|---------------------------------------------|
| API base URL           | `https://api.alphaxiv.org`                  |
| arXiv API              | Uses `arxiv` Python package                 |
| Default BFS iterations | 3                                           |
| Default similar limit  | 5                                           |
| Halls                  | `hall_facts`, `hall_discoveries`, `hall_questions`, `hall_methods`, `hall_context` |

---

## Test Results

### Unit Tests

All 28 unit tests pass (pytest):

```
$ python -m pytest tests/ -q
............................                                             [100%]
28 passed in 3.79s
```

**Test breakdown:**
- `test_client.py` -- 8 tests (API client, paper fetching, search)
- `test_cache.py` -- 7 tests (HTTP response caching)
- `test_graph.py` -- 7 tests (Obsidian note generation, paper ID sanitization)
- `test_overview_generator.py` -- 6 tests (Playwright browser automation)

### End-to-End CLI Tests

All commands tested against live APIs with real arXiv papers (2206.00364,
2011.13456, 2509.03853, 2505.01895):

| Command                              | Status | Notes                                                |
|--------------------------------------|--------|------------------------------------------------------|
| `axiv --help`                        | PASS   | Shows all commands                                   |
| `axiv version`                       | PASS   | `alphaxiv-cli 0.1.0`                                |
| `axiv init --force`                  | PASS   | Creates `.axiv`, `palace.sqlite3`                    |
| `axiv where`                         | PASS   | Resolves workspace correctly                         |
| `axiv search "diffusion..." -n 3`   | PASS   | Returns 3 results, table formatted                   |
| `axiv search "..." --json`          | PASS   | Valid JSON array output                              |
| `axiv get info 2206.00364`           | PASS   | Title, authors, abstract, categories                 |
| `axiv get overview 2206.00364`       | PASS   | AI-generated summary returned                        |
| `axiv get status 2206.00364`         | PASS   | `state: done`, translations shown                    |
| `axiv get metrics 2206.00364`        | FAIL   | HTTP 404 -- API does not serve metrics for this paper |
| `axiv get fulltext 2206.00364`       | FAIL   | HTTP 404 -- API does not serve fulltext for this paper |
| `axiv get all 2206.00364`            | PARTIAL| Info + overview succeed; metrics 404                 |
| `axiv similar main 2011.13456`       | PASS   | Returns similar papers                               |
| `axiv similar main 2206.00364`       | FAIL   | HTTP 404 -- API issue, not CLI bug                   |
| `axiv explore main 2011.13456 -d 1`  | PASS   | Discovers 3 papers at depth 1                        |
| `axiv research start wing ...`       | PASS   | 2/2 papers ingested, halls populated                 |
| `axiv research start wing ... -g`    | PASS   | Triggered overview generation, background poll completed |
| `axiv research wings`                | PASS   | Lists wing with paper count and date                 |
| `axiv research status wing`          | PASS   | Tree view: halls, rooms, tunnels, closets            |
| `axiv research room wing`            | PASS   | Lists 4 papers with note/report status               |
| `axiv research room wing 2206...`    | PASS   | Shows drawers for specific paper                     |
| `axiv research query wing "..."`     | PASS   | Returns ranked semantic search results               |
| `axiv research walk wing --hall`     | PASS   | Shows drawers organized by room within hall          |
| `axiv research expand wing -l 2`     | PASS   | Added 2 new papers via BFS                           |
| `axiv research link wing -v`         | PASS   | Linked 4/4 papers (with saved session)               |
| `axiv research link wing -v --secret`| PASS   | Linked 4/4 papers (with SECRET.md)                   |
| `axiv research trim wing --dry-run`  | PASS   | Shows similarity ranking, no deletions               |
| `axiv research trim wing --keep 2 --dry-run` | PASS | Marks bottom 2 for removal              |
| `axiv research synthesize wing -o`   | PASS   | Generates structured Markdown synthesis              |
| `axiv research visualize wing`       | PASS   | Outputs PNG + interactive HTML graph                 |

### Overview Generation Tests (with authentication)

| Test                                        | Status | Notes                        |
|---------------------------------------------|--------|------------------------------|
| Credential login (Google OAuth account)     | N/A    | Google blocks headless logins; use `axiv login` |
| Saved session login (`axiv login`)          | PASS   | Session persisted and reused headlessly |
| `ensure_overview_generated` (paper with no overview) | PASS | Generate button clicked, overview generated |
| `start -g` with saved session              | PASS   | Triggered generation, background poll detected completion |
| `link` with saved session                   | PASS   | "Using saved browser session" message shown, 2/2 linked |
| `link` with `--secret SECRET.md`           | PASS   | Credentials loaded, 4/4 linked |

**Legend:**
- PASS -- Command completed successfully with expected output
- FAIL -- API returned 404 (server-side issue, not a CLI bug)
- PARTIAL -- Some sub-requests failed due to API limitations
- N/A -- Not applicable (expected limitation)

### Known Limitations

- **Google blocks headless OAuth**: Accounts registered via Google OAuth cannot
  log in programmatically. Use `axiv login` for interactive login.
- `get metrics` and `get fulltext` return 404 for some papers -- these endpoints
  are not available for all papers on alphaxiv.org.
- `similar main` returns 404 for some papers (e.g., `2206.00364`) -- the
  similar-papers API does not cover all papers.
- These are server-side limitations, not CLI bugs. The CLI handles these errors
  gracefully with informative error messages.
