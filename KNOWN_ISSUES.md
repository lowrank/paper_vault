# Known Issues and Expected Behaviors

## Papers Without AI-Generated Overviews

### Behavior
When a paper does not have an AI-generated overview available from alphaXiv, the `graph` command will skip it with a clear message:

```
No overview for 2407.10654: API error: 404 - {"error":{"message":"Overviews not found","collection":"overviews"}}
Skipping 2407.10654 - no overview available
```

### Why This Happens
alphaXiv generates AI overviews on demand. Not all papers have overviews immediately available. This is expected behavior from the API.

### Impact on Graph Building

#### Starting Paper Has No Overview
If you start graph building with a paper that has no overview, **no notes will be generated**:

```bash
$ python -m alphaxiv_cli graph main 2407.10654 --iterations 2 --limit 5
Building knowledge graph: Inverse Physics-Informed Neural Networks...
Output: output
Iterations: 2, Limit: 5

  Skipping 2407.10654 - no overview available

✓ Generated 0 paper notes
```

**Why**: The graph command is specifically designed to build Obsidian notes from AI-generated overviews. Without an overview, there's no content to generate a note from.

#### Similar Papers May Have Overviews
When a starting paper has an overview but some of its similar papers don't, those papers are skipped while others are processed normally:

```bash
  [0] Processing: 2204.04602 (related_to=None)
  ✓ Generated note
  
  [1] Processing: 2406.02581 (related_to=2204.04602)
  Skipping 2406.02581 - no overview available
  
  [1] Processing: 2312.14688 (related_to=2204.04602)
  ✓ Generated note
```

This is expected and correct - the graph continues with papers that have overviews.

### Workarounds

#### 1. Use `similar` Command Instead
If you just want to explore connections without requiring overviews:

```bash
python -m alphaxiv_cli similar main 2407.10654 --depth 2 --limit 10
```

This shows paper connections without requiring overviews.

#### 2. Start with a Different Paper
Use a paper that has an overview available. Papers with overviews tend to be:
- More popular/highly cited
- Recently processed by alphaXiv
- From major conferences/journals

Test if a paper has an overview:
```bash
python -m alphaxiv_cli get overview <version_id>
```

#### 3. Request Overview from alphaXiv
Visit the paper on alphaxiv.org and the overview may be generated on-demand.

### Non-Issues

These are **NOT** bugs:
- ✅ Papers without overviews being skipped - Expected behavior
- ✅ Zero notes generated when starting paper has no overview - Expected behavior
- ✅ 404 errors for missing overviews - Expected API response
- ✅ Progress bar advancing on skipped papers - Correct behavior

### Actual Issues to Report

Please report these if you encounter them:
- ❌ CLI crashes when encountering missing overview
- ❌ Progress bar freezes on missing overview
- ❌ Cache corruption from 404 responses
- ❌ Similar papers not being fetched for papers WITH overviews

## Edge Cases Handled Correctly

### 1. Rate Limiting (429 Responses)
The client automatically retries with exponential backoff:
```
Attempt 1 failed (429) -> wait 1s -> retry
Attempt 2 failed (429) -> wait 2s -> retry
Attempt 3 failed (429) -> wait 4s -> retry
```

### 2. Network Timeouts
Configurable timeout (default 30s) with retry logic:
```python
client = AlphaXivClient(timeout=60.0, max_retries=5)
```

### 3. Malformed Responses
Gracefully handled with appropriate error messages.

### 4. Duplicate Papers
Tracked in `papers_db.json` - papers are only processed once.

### 5. Cache Corruption
If cache is corrupted, delete `.cache/alphaxiv/` and re-run.

## Performance Characteristics

### Cache Hit Performance
- First run: ~5-10s per paper (API calls)
- Cached run: ~0.1s per paper (instant)
- Cache TTL: 24 hours (configurable)

### Parallel Fetching
- Similar papers: Up to 5 concurrent requests
- Overviews: Up to 5 concurrent requests
- Configurable via `max_workers` parameter

### Progress Tracking Overhead
Minimal - Rich library is highly optimized.

## Future Enhancements

Potential improvements for handling papers without overviews:

1. **Fallback to Abstract-Only Notes**
   Generate minimal notes using just title + abstract for papers without overviews.

2. **Overview Request Triggering**
   Automatically trigger overview generation via alphaXiv API (if available).

3. **Mixed-Source Notes**
   Combine arXiv abstract, Semantic Scholar data, and OpenAlex metadata when overview unavailable.

4. **Queue Continuation**
   Option to continue BFS traversal even when current paper has no overview.

These are NOT currently implemented - the tool matches paper_vault's design philosophy of requiring AI-generated overviews for knowledge graph building.
