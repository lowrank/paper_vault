# AlphaXiv CLI

A command-line tool for interacting with the alphaXiv API, building structured
research knowledge bases from academic papers, and generating Obsidian-compatible
notes with AI-generated overviews.

---

## Installation

```bash
git clone <repository-url>
cd alphaxiv

pip install -e .

# Optional — required for AI overview generation
pip install playwright && playwright install chromium
```

After installation the `axiv` command is available globally.

---

## Workspace setup

Every command reads from and writes to a **workspace** — a directory containing
the palace database, vector store, notes, and cache.

```
Resolution order:
  Walk CWD upward looking for a .axiv marker file  →  local workspace
  No .axiv found anywhere                          →  ~/.alphaxiv (global fallback)
```

### `axiv init`

Initialise a local workspace in the current (or given) directory.

```bash
cd ~/research/diffusion-papers
axiv init                                   # init in CWD
axiv init ~/research/llm-papers             # init elsewhere
axiv init --notes ~/obsidian/papers         # custom notes location
axiv init --reports ~/obsidian/reports      # custom reports location
```

Creates a `.axiv` marker file. Every `axiv` command run inside this directory
tree automatically uses the local workspace — no extra flags needed.

### `axiv where`

Show which workspace is active and where all paths resolve.

```bash
axiv where
```

### Workspace layout

```
<workspace>/
  .axiv                     marker + path overrides (JSON)
  palace.sqlite3            research palace database
  palace/                   ChromaDB vector store
  knowledge_graph.sqlite3   citation / topic triples
  notes/                    Obsidian markdown notes
  reports/                  per-paper report notes
  cache/                    HTTP response cache (24 h TTL)
  browser-profile/          saved login session for overview generation
```

---

## Authentication (for AI overview generation)

AlphaXiv generates AI overviews only for logged-in users.  Because Google
OAuth blocks automated login attempts, the CLI uses a **persistent browser
session**: you log in once in a visible browser window and the session is
saved on disk.  All future runs reuse it headlessly.

### `axiv login`

```bash
axiv login
```

Opens Chromium at `alphaxiv.org/signin`.  Complete Google OAuth in the browser
window, then press **Enter** in the terminal.  The session is verified and
saved to `<workspace>/browser-profile/`.

Run this once per workspace.  Re-run if the session expires.

---

## Search

### `axiv search`

Search arXiv papers using the [arxiv.py](https://github.com/lukasschwab/arxiv.py)
library. Results are displayed in a table and you are prompted interactively to
select papers and start a research wing.

```bash
axiv search "score matching generative models"
axiv search "ti:consistency models" --limit 5
axiv search "au:song AND cat:cs.LG" --sort lastUpdatedDate
axiv search "cat:math.AP" --cat math.AP   # strict category filter
axiv search "diffusion" --json | jq '.[].paper_id'
```

**Query syntax** (arXiv search grammar):

| Prefix | Matches |
|--------|---------|
| *(none)* | title + abstract full-text |
| `ti:` | title |
| `au:` | author |
| `cat:` | category (any, including cross-listings) |
| `AND` / `OR` | boolean combination |

**Options**:

| Flag | Default | Description |
|------|---------|-------------|
| `--limit, -n` | 10 | Number of results |
| `--sort, -s` | relevance | `relevance` \| `lastUpdatedDate` \| `submittedDate` |
| `--cat` | — | Post-filter: keep only papers where this category appears in their list |
| `--json, -j` | off | JSON output (skips interactive prompt) |

**Note on `cat:` queries**: arXiv matches `cat:` against *all* categories
including cross-listings.  A paper with primary `math.MG` can appear for
`cat:math.AP` if it is cross-listed.  The table shows the full category list
so you can see why each result matched.  Use `--cat math.AP` to post-filter.

### Interactive wing creation

After results are shown, a checkbox prompt lets you select papers and
immediately start a research wing:

```
? Select papers to add to a research wing:
  ◉  [2011.13456]  Score-Based Generative Modeling…
  ◉  [2006.11239]  Denoising Diffusion Probabilistic Models
  ○  [2010.02502]  Denoising Diffusion Implicit Models

Suggested wing names (from 2 selected paper(s)):
  Label  →  Score-based Generative Diffusion Probabilistic
  Slug   →  score-based-generative-diffusion

? Wing label — edit or press Enter to accept:  Score-based Diffusion Models
? Wing slug  — edit or press Enter to accept:  score-diffusion
? Start this wing? (Y/n)
```

The **label** is a long human-readable description stored as the wing topic.
The **slug** is the short identifier used in all subsequent commands
(`axiv research <slug>`). Both are suggested automatically from the selected
paper titles and can be freely edited.

---

## Research Palace

The Research Palace is a structured, persistent memory store for academic
papers, inspired by the [memory palace](https://github.com/milla-jovovich/mempalace/)
technique.

### Concepts

| Term | Meaning |
|------|---------|
| **Wing** | One research session / topic (identified by its slug) |
| **Hall** | Memory-type corridor: `hall_facts`, `hall_discoveries`, `hall_questions`, `hall_methods`, `hall_context` |
| **Room** | One paper inside a wing |
| **Closet** | Distilled one-line summary of a room pointing to its drawers |
| **Drawer** | Verbatim content chunk (abstract, citation justification, overview excerpt, …) |
| **Tunnel** | Directed connection between rooms (`cites` / `similar`) |

### `axiv research start`

Begin or resume a wing with one or more seed papers.

```bash
axiv research start <wing> <id> [<id>…] [--topic "…"] [--verbose]
```

```bash
axiv research start score-diffusion 2011.13456 2006.11239 \
  --topic "Score-based and diffusion generative models"
```

### `axiv research expand`

BFS-expand a wing by following similar-paper links.

```bash
axiv research expand score-diffusion --limit 3 --hops 2
```

### `axiv research room`

Without a paper ID: list all rooms (papers) in the wing with note-link status.  
With a paper ID: enter that room and read all drawers.

```bash
axiv research room score-diffusion                       # list all rooms
axiv research room score-diffusion --linked              # only linked rooms
axiv research room score-diffusion 2011.13456            # enter room
axiv research room score-diffusion 2011.13456 --hall hall_facts
axiv research room score-diffusion 2011.13456 --full     # no truncation
```

### `axiv research query`

Semantic search inside a wing (or across all wings).

```bash
axiv research query score-diffusion "how is the noise schedule used"
axiv research query score-diffusion "denoising objective" --hall hall_methods
axiv research query score-diffusion "fast sampling" --top 6 --all
```

### `axiv research walk`

Walk through a hall corridor and read all its drawers.

```bash
axiv research walk score-diffusion --hall hall_facts
axiv research walk score-diffusion --hall hall_context --paper 2011.13456
```

### `axiv research link`

Generate Obsidian notes for every paper in the wing and store the file paths
back in the palace.

Papers **with** an existing AI overview are linked immediately.  
Papers **without** one trigger browser automation to request generation
(requires a saved login session from `axiv login`).

```bash
axiv research link score-diffusion
axiv research link score-diffusion --output ~/obsidian/papers
axiv research link score-diffusion --background        # detach to background
axiv research link score-diffusion --relink            # regenerate all notes
axiv research link score-diffusion --no-headless       # visible browser (debug)
```

Progress for background runs tails via:
```bash
tail -f <notes-dir>/link.log
```

### `axiv research synthesize`

Distil the entire wing into a structured Markdown synthesis note.

```bash
axiv research synthesize score-diffusion
axiv research synthesize score-diffusion --output synthesis.md
```

The output includes: palace map (closet index), per-hall synthesis with full
drawer content, open questions, cross-paper tunnel graph, and Obsidian
`[[wiki-links]]` to linked notes and reports wherever available.

### `axiv research visualize`

Render the paper graph as a PNG and/or interactive HTML file.

```bash
axiv research visualize score-diffusion --output ./graphs
axiv research visualize score-diffusion --format html
axiv research visualize score-diffusion --format png
```

Node colours: **blue** = seed papers, **orange** = discovered via expand,
**green** = external cited papers not in the wing.  
Edge labels: `similar` or `cites`.

The HTML file is self-contained (vis-network from CDN) — open in any browser,
drag nodes, zoom, hover for full titles.

### `axiv research status`

Wing overview tree: halls, room counts, tunnel count, closet index.

```bash
axiv research status                     # all wings
axiv research status score-diffusion     # one wing
axiv research status score-diffusion --json
```

### `axiv research wings`

List all research wings in the palace.

```bash
axiv research wings
```

---

## Paper commands

```bash
axiv get info 2204.04602          # metadata
axiv get overview 2204.04602      # AI overview
axiv get all 2204.04602           # info + overview + metrics + resources
axiv get status 2204.04602        # overview generation status
axiv get metrics 2204.04602
axiv get fulltext 2204.04602 -o fulltext.txt

axiv similar main 2204.04602 --limit 5
axiv similar main 2204.04602 --depth 2    # BFS traversal
```

---

## Knowledge graph (Obsidian notes)

```bash
axiv graph main <paper_id> \
  --iterations 3 \
  --limit 5 \
  --images \
  --verbose \
  --generate \
  --secret SECRET.md \
  -o output/
```

Output structure:

```
output/
  {paper_id}.md               main Obsidian note
  reports/{paper_id}_report.md
  images/{paper_id}/*.jpeg    (if --images)
  papers_db.json
```

Notes include YAML frontmatter, Obsidian callouts (`[!abstract]`, `[!note]`,
`[!quote]`, `[!tip]`), wiki-links to related papers, key citations with
justifications, and topic keywords.

---

## Tab completion

Install once to enable `<Tab>` completion for wing names and hall names:

```bash
# zsh
axiv --install-completion zsh
source ~/.zshrc

# bash
axiv --install-completion bash
source ~/.bashrc
```

After installation:

```bash
axiv research status <Tab>          # lists wing names
axiv research query diff<Tab>       # completes to diffusion-models
axiv research query w --hall <Tab>  # lists hall names
```

---

## Architecture

```
alphaxiv/
  __main__.py              CLI entry point (axiv)
  client.py                AlphaXiv + arXiv API client
  config.py                Global constants / defaults
  context.py               Workspace resolution (.axiv discovery)
  overview_generator.py    Playwright browser automation
  commands/
    get.py                 axiv get …
    similar.py             axiv similar …
    explore.py             axiv explore …
    graph.py               axiv graph … (Obsidian KG builder)
    research.py            axiv research … (Research Palace)
  storage/
    cache.py               File-based HTTP cache
    memory.py              ChromaDB + KG triple helpers
    palace.py              Research Palace SQLite layer
  utils/
    helpers.py             ID extraction, misc
    naming.py              Wing name extraction from paper titles
```

---

## API reference

| Endpoint | Used for |
|----------|---------|
| `GET /papers/v3/{id}` | Paper metadata |
| `GET /papers/v3/{versionId}/overview/en` | AI overview |
| `GET /papers/v3/{id}/similar-papers` | Similarity graph |
| `GET /papers/v3/{versionId}/metrics` | View / citation counts |
| `GET /papers/v3/{versionId}/full-text` | Full paper text |
| `POST /papers/v3/{id}/overview/request` | Request overview generation |
| `export.arxiv.org/api/query` | arXiv search (via arxiv.py) |

Old-style arXiv IDs (e.g. `math/0504536`) are URL-encoded automatically so
they resolve correctly.
