# Feature Comparison: alphaxiv_cli vs paper_vault

## Core Features from paper_vault build_knowledge.py

### ✓ IMPLEMENTED

1. **BFS Graph Traversal**
   - Status: ✓ Fully implemented
   - Location: `commands/graph.py` build_graph()
   - Notes: Same depth-based queue system with (paper_id, depth, related_to) tuples

2. **Overview Fetching**
   - Status: ✓ Implemented
   - Location: `client.py` get_overview()
   - Notes: API endpoint matches

3. **Similar Papers**
   - Status: ✓ Implemented
   - Location: `client.py` get_similar_papers()
   - Notes: Same API, with limit parameter

4. **Image Downloading**
   - Status: ✓ Implemented
   - Location: `commands/graph.py` download_images_from_markdown()
   - Notes: Same pattern matching, local path rewriting

5. **arXiv Categories Fetching**
   - Status: ✓ Implemented
   - Location: `commands/graph.py` get_arxiv_categories()
   - Notes: Same arXiv API query, category filtering

6. **Keyword Extraction**
   - Status: ✓ Implemented
   - Location: `commands/graph.py` extract_keywords()
   - Notes: Extracts from aiTooltips and topics

7. **Database Tracking**
   - Status: ✓ Implemented
   - Location: `commands/graph.py` load_db(), save_db()
   - Notes: papers_db.json with same structure

8. **Duplicate Detection**
   - Status: ✓ Implemented
   - Location: `commands/graph.py` via db tracking
   - Notes: Skips already processed papers

9. **Intermediate Reports**
   - Status: ✓ Implemented
   - Location: `commands/graph.py` build_note()
   - Notes: Separate reports/ directory

10. **Obsidian Markdown Format**
    - Status: ✓ Implemented
    - Frontmatter: ✓ (date, tags, arxiv)
    - Callouts: ✓ ([!abstract], [!note], [!quote], [!tip])
    - Wiki-links: ✓ ([[paper_id.md|title]])
    - Citations: ✓ With justifications

11. **Progress Tracking**
    - Status: ✓ Enhanced (rich progress bars)
    - paper_vault: Simple print statements
    - alphaxiv_cli: Rich progress bars with percentages

12. **Caching**
    - Status: ✓ Enhanced
    - paper_vault: No caching
    - alphaxiv_cli: Full HTTP response caching with TTL

### ⚠ PARTIALLY IMPLEMENTED

13. **Overview Generation (NEW - Just Added)**
    - Status: ⚠ Partially implemented
    - Location: `overview_generator.py` ensure_overview_generated()
    - Missing: Integration into graph command with --generate flag
    - Notes: Code written but not wired up yet

### ✗ MISSING FEATURES

14. **Playwright Login/Browser Automation**
    - Status: ⚠ Code written, needs integration
    - paper_vault: Full login flow in ensure_overview_generated()
    - alphaxiv_cli: Module created but not integrated into graph command
    - Action needed: Wire up --generate flag to call ensure_overview_generated()

15. **Credentials Management**
    - Status: ⚠ Code written, needs integration
    - paper_vault: Reads from SECRET.md (email: / passwd:)
    - alphaxiv_cli: Supports both SECRET.md and env vars (ALPHAXIV_EMAIL, ALPHAXIV_PASSWORD)
    - Action needed: Document and test

16. **Browser Profile Persistence**
    - Status: ⚠ Code written
    - paper_vault: BROWSER_PROFILE = ~/.alphaxiv/browser-profile-login
    - alphaxiv_cli: Same location in overview_generator.py
    - Action needed: Test login persistence

## Additional Features in alphaxiv_cli (Enhancements)

### ✓ NEW FEATURES

1. **Multiple Commands**
   - `get` - Fetch individual paper data
   - `similar` - Find similar papers
   - `explore` - Deep exploration
   - `graph` - Build knowledge graph
   - `search` - Search papers

2. **Parallel Fetching**
   - `get_similar_papers_batch()` - Concurrent similar paper fetching
   - `get_overviews_batch()` - Concurrent overview fetching
   - ThreadPoolExecutor with configurable workers

3. **HTTP Response Caching**
   - File-based cache with TTL
   - Automatic cache invalidation
   - Faster repeat queries

4. **Progress Bars**
   - Rich library integration
   - Real-time progress updates
   - Iteration tracking

5. **CLI Entry Point**
   - `axiv` command alias
   - Typer-based CLI with help
   - Better UX than raw script

6. **JSON Output**
   - `--json` flag for structured output
   - Useful for scripting

## Critical Missing Integration

### TODO: Wire up overview generation

The overview generation code exists but is NOT called by the graph command.

**Current state:**
```python
# commands/graph.py line ~187-198
try:
    overview = client.get_overview(version_id)
except Exception as e:
    if verbose:
        print(f"  No overview for {paper_id}: {e}")
    overview = None

if not overview or not overview.get('overview'):
    if verbose:
        print(f"  Skipping {paper_id} - no overview available")
    progress.advance(task)
    continue  # <-- Just skips the paper
```

**Should be:**
```python
try:
    overview = client.get_overview(version_id)
except Exception as e:
    if verbose:
        print(f"  No overview for {paper_id}: {e}")
    overview = None
    
    # NEW: Try to generate if flag is set
    if generate_missing:
        secret_path = Path(secret_file) if secret_file else None
        if ensure_overview_generated(paper_id, version_id, client, secret_path):
            try:
                overview = client.get_overview(version_id)
            except:
                overview = None

if not overview or not overview.get('overview'):
    if verbose:
        print(f"  Skipping {paper_id} - no overview available")
    progress.advance(task)
    continue
```

## Command-Line Argument Comparison

### paper_vault
```bash
python build_knowledge.py <paper_id> [--date YYYY-MM-DD] [--iterations N]
```

### alphaxiv_cli
```bash
python -m alphaxiv_cli graph main <paper_id> \
  --output DIR \
  --iterations N \
  --limit N \
  --verbose \
  --images \
  --generate        # <-- NEW, needs wiring
  --secret PATH     # <-- NEW, needs wiring
```

## Summary

**Total Features**: 16
- ✓ Fully Implemented: 12
- ⚠ Partially Implemented: 4 (code written, needs integration)
- ✗ Missing: 0

**Action Items**:
1. Wire up `--generate` flag in graph command
2. Integrate `ensure_overview_generated()` call
3. Pass `secret_file` parameter through
4. Update build_graph() to accept generate_missing parameter
5. Test with paper 2407.10654
6. Document Playwright installation and credentials

**Enhancement Status**: alphaxiv_cli has ALL paper_vault features PLUS extras (caching, progress bars, parallel fetching, multiple commands, CLI UX).
