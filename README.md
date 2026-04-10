# AlphaXiv CLI

A powerful command-line tool for interacting with the alphaXiv API, building knowledge graphs from research papers, and generating Obsidian-compatible markdown notes with AI-generated overviews.

## Features

- 🚀 **Caching**: Automatic API response caching (24h TTL) for faster repeat queries
- 📊 **Progress Bars**: Rich progress indicators for long-running operations
- ⚡ **Parallel Fetching**: Concurrent API requests for similar papers and overviews
- 🖼️ **Image Downloads**: Optional local image downloading from overviews
- 📝 **Obsidian Notes**: Generate Obsidian-compatible markdown with wiki-links and callouts
- 🔍 **BFS Traversal**: Explore paper connections at multiple depths
- 💾 **Database Tracking**: Avoid duplicate processing with papers_db.json
- 🤖 **Auto-generation**: Automatically generate missing overviews via browser automation (Playwright)

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd alphaxiv-cli-tool

# Install dependencies
pip install -r requirements.txt

# Install package (editable mode for development)
pip install -e .

# Install Playwright for auto-generation feature (optional)
pip install playwright
playwright install chromium
```

## Quick Start

```bash
# Get paper information
python -m alphaxiv_cli get info 2204.04602

# Get AI-generated overview
python -m alphaxiv_cli get overview 2204.04602

# Find similar papers
python -m alphaxiv_cli similar main 2204.04602 --limit 5

# Build Obsidian knowledge graph
python -m alphaxiv_cli graph main 2204.04602 --iterations 3 --images -v

# Auto-generate missing overviews
python -m alphaxiv_cli graph main 2407.10654 --generate --secret SECRET.md
```

## Usage

> **Note**: All commands can be run with `python -m alphaxiv_cli` or the shorthand `axiv` (after installation)

### Get Paper Information

```bash
# Get basic info
python -m alphaxiv_cli get info 2204.04602

# Get overview
python -m alphaxiv_cli get overview 2204.04602

# Get all data at once (info + overview + metrics + resources)
python -m alphaxiv_cli get all 2204.04602

# Check overview generation status
python -m alphaxiv_cli get status 2204.04602

# Get metrics
python -m alphaxiv_cli get metrics 2204.04602

# Get full text
python -m alphaxiv_cli get fulltext 2204.04602 -o fulltext.txt
```

### Find Similar Papers

```bash
# Get similar papers
python -m alphaxiv_cli similar main 2204.04602

# Limit results
python -m alphaxiv_cli similar main 2204.04602 --limit 5

# BFS traversal (similar-of-similar)
python -m alphaxiv_cli similar main 2204.04602 --depth 2
```

### Build Knowledge Graph (Obsidian Notes)

```bash
# Basic usage
python -m alphaxiv_cli graph main 2204.04602

# With all features
python -m alphaxiv_cli graph main <paper_id> \
  --iterations 3 \
  --limit 5 \
  --images \
  --verbose \
  --generate \
  --secret SECRET.md \
  --headless \
  -o output/
```

**Options**:
- `--iterations, -n`: Number of BFS iterations (default: 3)
- `--limit, -l`: Similar papers per paper (default: 5)
- `--images`: Download images locally
- `--verbose, -v`: Detailed progress output
- `--generate, -g`: Auto-generate missing overviews (requires Playwright + credentials)
- `--secret`: Path to SECRET.md with credentials
- `--headless/--no-headless`: Run browser in headless mode (default: visible)
- `--output, -o`: Output directory (default: output/)

### Overview Auto-generation

To enable auto-generation of missing overviews:

1. **Install Playwright**:
```bash
pip install playwright
playwright install chromium
```

2. **Set up credentials** (choose one):

**Option A: Environment variables**
```bash
export ALPHAXIV_EMAIL="your.email@gmail.com"
export ALPHAXIV_PASSWORD="your_password"
```

**Option B: SECRET.md file**
```
email: your.email@gmail.com
password: your_password
```

3. **Use the `--generate` flag**:
```bash
python -m alphaxiv_cli graph main 2407.10654 --generate --secret SECRET.md
```

## Advanced Features

### Caching System

API responses are automatically cached to `.cache/alphaxiv/` with a 24-hour TTL. This dramatically speeds up repeat queries and reduces API load.

```bash
# First run - fetches from API
python -m alphaxiv_cli graph main 2204.04602

# Second run - uses cache (much faster)
python -m alphaxiv_cli graph main 2204.04602
```

Cache can be customized via client initialization:
```python
from alphaxiv_cli.client import AlphaXivClient

client = AlphaXivClient(
    cache_dir=".my-cache",  # Custom cache location
    cache_ttl=48            # Custom TTL in hours
)
```

### Parallel Fetching

The client supports batch operations for fetching multiple papers concurrently:

```python
# Fetch similar papers for multiple papers in parallel
results = client.get_similar_papers_batch(
    paper_ids=["2204.04602", "2312.14688"],
    limit=10,
    max_workers=5  # Concurrent threads
)

# Fetch overviews in parallel
overviews = client.get_overviews_batch(
    version_ids=["version-1", "version-2"],
    max_workers=5
)
```

### Progress Tracking

Long-running operations display rich progress bars automatically:
- Iteration progress (Iteration 1/3)
- Paper processing status
- Real-time updates on current paper

## Architecture

```
alphaxiv_cli/
├── __init__.py           # Package metadata
├── __main__.py           # CLI entry point
├── client.py             # AlphaXiv API client with caching & parallel support
├── commands/
│   ├── get.py            # Get paper data
│   ├── similar.py        # Find similar papers
│   ├── explore.py        # Deep exploration
│   └── graph.py          # Build Obsidian notes with progress bars
├── storage/
│   ├── cache.py          # File-based caching system
│   └── __init__.py
└── requirements.txt
```

## Output Format

### Obsidian Notes Structure

```
output/
├── {paper_id}.md              # Main paper note
├── reports/
│   └── {paper_id}_report.md  # Detailed intermediate report
├── images/
│   └── {paper_id}/           # Downloaded images (if --images flag)
│       └── *.jpeg
└── papers_db.json            # Processed papers database
```

### Markdown Features

- **YAML Frontmatter**: Date, tags (arXiv categories), arXiv ID
- **Obsidian Callouts**: `[!abstract]`, `[!note]`, `[!quote]`, `[!tip]`
- **Wiki-links**: `[[paper_id.md|title]]` for cross-references
- **Related Papers**: Automatic linking to similar papers
- **Key Citations**: Extracted with importance justifications
- **Topics/Keywords**: Auto-extracted from AI tooltips

## API Endpoints

- `GET /papers/v3/{id}` - Paper info
- `GET /papers/v3/{versionId}/overview/{lang}` - AI overview
- `GET /papers/v3/{id}/similar-papers` - Similar papers
- `GET /papers/v3/{versionId}/metrics` - Paper metrics
- `GET /papers/v3/{versionId}/full-text` - Full text
- `GET /papers/v3/search` - Search papers

## Integration with paper_vault

This CLI extends the [paper_vault](https://github.com/lowrank/paper_vault) functionality:

- Same API endpoints
- Enhanced CLI UX with typer
- BFS traversal for knowledge graph building
- Obsidian-compatible output format
