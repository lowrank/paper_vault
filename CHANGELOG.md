# Changelog

## v0.1.0 - 2026-04-10

### Features

#### 🚀 Caching System
- Automatic API response caching with 24-hour TTL
- Cache stored in `.cache/alphaxiv/` directory
- Customizable cache location and TTL
- Dramatically speeds up repeat queries

#### 📊 Progress Bars
- Rich progress indicators using `rich` library
- Real-time iteration and paper processing status
- Visual feedback for long-running operations
- Shows current paper being processed

#### ⚡ Parallel Fetching
- Concurrent API requests using ThreadPoolExecutor
- `get_similar_papers_batch()` - Fetch multiple papers in parallel
- `get_overviews_batch()` - Batch overview fetching
- Configurable max_workers (default: 5)

#### 🖼️ Image Downloads
- `--images` flag to download images from overviews
- Images saved to `output/images/{paper_id}/`
- Automatic path rewriting in markdown
- Obsidian-compatible relative paths

#### 📝 Obsidian Notes
- YAML frontmatter with date, tags, arXiv ID
- Obsidian callouts: `[!abstract]`, `[!note]`, `[!quote]`, `[!tip]`
- Wiki-links for cross-references: `[[paper_id.md|title]]`
- Intermediate reports in separate `reports/` directory
- Auto-extracted keywords from AI tooltips
- arXiv category tags from arXiv API

#### 🔍 BFS Traversal
- Multi-level paper connection exploration
- Configurable iterations and similarity limit
- Database tracking to avoid duplicates (`papers_db.json`)

#### 💻 CLI
- Multiple commands: get, similar, explore, graph, search
- JSON and text output formats
- Verbose mode for detailed logging
- Entry point alias: `axiv` (after proper installation)

### API Client

#### AlphaXivClient
- Retry logic with exponential backoff
- Rate limiting handling (429 responses)
- Timeout configuration
- Cache integration
- Batch methods for parallel operations

### Storage

#### Cache
- File-based JSON caching
- TTL-based expiration
- get/set interface

#### PaperDatabase
- Track processed papers
- Avoid duplicate processing
- Metadata storage (title, date, processed status)

### Documentation

- Comprehensive README with usage examples
- Architecture documentation
- Feature descriptions
- Integration notes with paper_vault

### Testing

All commands tested and verified:
- ✓ Version command
- ✓ Get info/overview/metrics
- ✓ Similar papers
- ✓ Graph building with progress bars
- ✓ Caching (cache hits verified)
- ✓ Image downloads
- ✓ Obsidian markdown format

### Known Issues

- `axiv` alias requires proper installation (not editable mode)
- Some papers may not have overviews available (404 responses)
- LSP import warnings in development (runtime works correctly)

### Dependencies

- httpx >= 0.27.0
- typer >= 0.12.0
- rich >= 12.3.0 (already included via typer)

### File Structure

```
alphaxiv_cli/
├── __init__.py           # Package metadata (v0.1.0)
├── __main__.py           # CLI entry point
├── client.py             # API client with caching & parallel support
├── commands/
│   ├── __init__.py
│   ├── get.py            # Get paper data
│   ├── similar.py        # Find similar papers
│   ├── explore.py        # Deep exploration
│   └── graph.py          # Build Obsidian notes
├── storage/
│   ├── __init__.py
│   └── cache.py          # Caching system
├── setup.py              # Package configuration
├── requirements.txt      # Dependencies
├── README.md             # Usage documentation
├── IMPLEMENTATION.md     # Technical details
├── EXAMPLES.md           # Usage examples
└── CHANGELOG.md          # This file
```

### Credits

Based on [paper_vault](https://github.com/lowrank/paper_vault) by lowrank.
Enhanced with CLI interface, caching, progress tracking, and parallel fetching.
