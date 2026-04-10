# Code Quality Improvement Tasks

Generated: 2026-04-10
Status: Actionable backlog for alphaxiv-cli-tool

---

## HIGH PRIORITY (Security & Correctness)

### SEC-001: Replace Bare Except Blocks with Specific Exception Handling
**Status**: TODO  
**Priority**: High  
**Effort**: 2-3 hours  
**Impact**: Critical - Silent failures make debugging impossible

**Description**:
Replace 9 bare `except:` blocks across the codebase with specific exception handlers and proper logging.

**Acceptance Criteria**:
- [ ] All bare `except:` blocks replaced with specific exceptions
- [ ] Each exception logged with appropriate level (debug/warning/error)
- [ ] No silent failures (all exceptions either logged or re-raised)
- [ ] Logging module configured at package level

**Files Affected**:
- `overview_generator.py`: lines 53, 86-92, 129-135, 171-179, 187-194
- `storage/cache.py`: line 27-37
- `commands/graph.py`: lines 81-91, 192-208
- `commands/explore.py`: lines 78-83
- `client.py`: lines 76-80, 186-197, 211-216

**Implementation Notes**:
```python
# BAD
try:
    overview = client.get_overview(version_id)
except:
    pass

# GOOD
import logging
logger = logging.getLogger(__name__)

try:
    overview = client.get_overview(version_id)
except httpx.TimeoutError as e:
    logger.debug(f"Timeout fetching overview for {version_id}: {e}")
    overview = None
except AlphaXivError as e:
    logger.warning(f"API error fetching overview: {e}")
    overview = None
except Exception as e:
    logger.error(f"Unexpected error fetching overview: {e}", exc_info=True)
    overview = None
```

---

### SEC-002: Add Logging Infrastructure
**Status**: TODO  
**Priority**: High  
**Effort**: 1-2 hours  
**Impact**: High - Enables debugging and monitoring

**Description**:
Configure package-level logging with appropriate handlers and formatters. Replace all `print()` debug statements with logging calls.

**Acceptance Criteria**:
- [ ] Logging configured in `__init__.py`
- [ ] All debug `print()` statements replaced with `logger.debug()`
- [ ] Error messages use `logger.error()`
- [ ] User-facing messages remain as `print()` (e.g., progress updates)
- [ ] Log level configurable via environment variable

**Files Affected**:
- All files (package-wide change)

**Implementation Notes**:
```python
# alphaxiv_cli/__init__.py
import logging
import os

log_level = os.getenv("ALPHAXIV_LOG_LEVEL", "WARNING")
logging.basicConfig(
    level=getattr(logging, log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
```

---

### PERF-001: Batch Database Writes in BFS Loop
**Status**: TODO  
**Priority**: High  
**Effort**: 1 hour  
**Impact**: Medium - Reduces I/O overhead significantly

**Description**:
`build_graph()` calls `save_db()` after processing each paper, causing excessive disk I/O. Batch writes every N papers or per iteration.

**Acceptance Criteria**:
- [ ] Database written every 10 papers or at end of iteration (whichever comes first)
- [ ] Final write at end of traversal
- [ ] No data loss if process interrupted (write on signals)

**Files Affected**:
- `commands/graph.py`: lines 229-231

**Implementation Notes**:
```python
# Inside build_graph()
processed_since_save = 0

while queue:
    # ... process paper
    db[paper_id] = {...}
    processed += 1
    processed_since_save += 1
    
    if processed_since_save >= 10:
        save_db(db_file, db)
        processed_since_save = 0

# After loop
save_db(db_file, db)  # Final save
```

---

## MEDIUM PRIORITY (Code Quality & Maintainability)

### REFACTOR-001: Extract Repeated Version ID Logic
**Status**: TODO  
**Priority**: Medium  
**Effort**: 30 minutes  
**Impact**: Medium - Reduces duplication

**Description**:
Version ID extraction pattern repeated across 8+ locations. Extract to helper function.

**Acceptance Criteria**:
- [ ] Helper function `extract_version_id(info: Dict) -> Optional[str]` created
- [ ] All repeated patterns replaced with helper call
- [ ] Type hints added

**Files Affected**:
- `commands/get.py`: lines 28-31, 74-77, etc.
- `commands/graph.py`: lines 187-190
- `commands/explore.py`: lines 26-33

**Implementation Notes**:
```python
# utils/helpers.py
from typing import Dict, Optional, Any

def extract_version_id(info: Dict[str, Any]) -> Optional[str]:
    return info.get("versionId") or info.get("version_id")
```

---

### REFACTOR-002: Centralize Constants and Configuration
**Status**: TODO  
**Priority**: Medium  
**Effort**: 1 hour  
**Impact**: Medium - Makes configuration manageable

**Description**:
Magic numbers and hardcoded values scattered throughout. Centralize in `config.py`.

**Acceptance Criteria**:
- [ ] `config.py` created with all constants
- [ ] Constants use descriptive names (not magic numbers)
- [ ] Environment variable overrides documented
- [ ] Default values well-commented

**Files Affected**:
- All files

**Implementation Notes**:
```python
# config.py
import os

# API
BASE_API_URL = os.getenv("ALPHAXIV_API_URL", "https://api.alphaxiv.org")
USER_AGENT = "alphaxiv-cli/1.0"

# Cache
DEFAULT_CACHE_DIR = ".cache/alphaxiv"
DEFAULT_CACHE_TTL_HOURS = 24

# HTTP Client
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RETRIES = 3
RATE_LIMIT_BACKOFF_BASE = 2

# Playwright
BROWSER_PROFILE_DIR = os.path.expanduser("~/.alphaxiv/browser-profile-login")
PLAYWRIGHT_TIMEOUT_MS = 15000
LOGIN_MAX_WAIT_SECONDS = 90
OVERVIEW_GENERATION_TIMEOUT_SECONDS = 90
OVERVIEW_POLL_INTERVAL_SECONDS = 1

# BFS
DEFAULT_BFS_ITERATIONS = 3
DEFAULT_SIMILAR_LIMIT = 5
```

---

### TYPE-001: Add Type Hints to Public APIs
**Status**: TODO  
**Priority**: Medium  
**Effort**: 2 hours  
**Impact**: Medium - Enables static analysis

**Description**:
Many public functions lack type hints. Add comprehensive type annotations.

**Acceptance Criteria**:
- [ ] All public functions have complete type hints
- [ ] Return types specified
- [ ] `mypy` or `pyright` runs without errors
- [ ] `Optional` and `Union` used appropriately

**Files Affected**:
- `overview_generator.py`: check_login, login_to_alphaxiv, ensure_overview_generated
- `commands/graph.py`: build_graph, build_note, download_images_from_markdown
- `commands/*.py`: All command functions

**Implementation Notes**:
```python
from typing import Optional, Dict, Any, Tuple, List
from playwright.sync_api import Page

def check_login(page: Page) -> bool:
    ...

def login_to_alphaxiv(page: Page, email: str, password: str) -> bool:
    ...

def ensure_overview_generated(
    paper_id: str,
    version_id: str,
    client: AlphaXivClient,
    secret_file: Optional[Path] = None,
    headless: bool = True
) -> bool:
    ...
```

---

### REFACTOR-003: Improve CachedResponse Class
**Status**: TODO  
**Priority**: Medium  
**Effort**: 30 minutes  
**Impact**: Low - Prevents potential bugs

**Description**:
`CachedResponse` mock in `client.py` only implements `status_code` and `json()`, missing `.text` attribute. Make it fully compatible.

**Acceptance Criteria**:
- [ ] CachedResponse implements all necessary httpx.Response attributes
- [ ] `.text` property added
- [ ] `.headers` property added (empty dict)
- [ ] Unit tests cover cached response usage

**Files Affected**:
- `client.py`: lines 51-57

**Implementation Notes**:
```python
class CachedResponse:
    def __init__(self, data: Dict[str, Any]):
        self.status_code = 200
        self._data = data
        self.headers = {}
    
    def json(self) -> Dict[str, Any]:
        return self._data
    
    @property
    def text(self) -> str:
        import json
        return json.dumps(self._data)
```

---

## LOW PRIORITY (Nice to Have)

### ENHANCE-001: Use Stable Hash for Image Filenames
**Status**: TODO  
**Priority**: Low  
**Effort**: 15 minutes  
**Impact**: Low - Consistency across runs

**Description**:
`hash(url) % 10000` in image downloads uses Python's non-stable hash, causing inconsistent filenames across runs. Use `hashlib.sha256` instead.

**Acceptance Criteria**:
- [ ] Image filenames stable across runs
- [ ] No hash collisions within reasonable limits
- [ ] Filenames remain reasonably short

**Files Affected**:
- `commands/graph.py`: line 130

**Implementation Notes**:
```python
import hashlib

safe_name = re.sub(r'[^\w\-]', '_', alt_text[:30]) if alt_text else hashlib.sha256(url.encode()).hexdigest()[:12]
```

---

### ENHANCE-002: Improve Playwright Wait Strategy
**Status**: TODO  
**Priority**: Low  
**Effort**: 2 hours  
**Impact**: Low - More reliable automation

**Description**:
Replace `time.sleep()` and `page.wait_for_timeout()` with deterministic waits (`wait_for_selector`, `wait_for_load_state`) and exponential backoff for polling.

**Acceptance Criteria**:
- [ ] No arbitrary `time.sleep()` calls
- [ ] Use `wait_for_selector` with explicit timeouts
- [ ] Overview generation polling uses exponential backoff
- [ ] Total wait time remains reasonable

**Files Affected**:
- `overview_generator.py`: lines 50, 62, 67, 75, 83, 96-103, 166-196

**Implementation Notes**:
```python
# Instead of time.sleep(5)
page.wait_for_load_state("networkidle", timeout=5000)

# Exponential backoff for overview polling
import time
backoff = 1
for attempt in range(60):
    time.sleep(backoff)
    if check_condition():
        break
    backoff = min(backoff * 1.5, 5)  # Cap at 5 seconds
```

---

### DOC-001: Add CONTRIBUTING.md
**Status**: TODO  
**Priority**: Low  
**Effort**: 1 hour  
**Impact**: Low - Helps contributors

**Description**:
Document development setup, coding standards, and testing requirements.

**Acceptance Criteria**:
- [ ] Development setup instructions
- [ ] Code style guide (follow existing patterns)
- [ ] Testing requirements (100% coverage for new code)
- [ ] PR process documented

---

## TESTING TASKS

### TEST-001: Increase Test Coverage to 80%+
**Status**: TODO  
**Priority**: Medium  
**Effort**: 4-6 hours  
**Impact**: High - Prevents regressions

**Description**:
Current test suite covers core modules. Expand to CLI commands and edge cases.

**Acceptance Criteria**:
- [ ] Coverage >= 80% for all modules
- [ ] All CLI commands have integration tests
- [ ] Edge cases covered (network failures, malformed responses)
- [ ] CI/CD runs tests automatically

**New Test Files Needed**:
- `test_cli_integration.py` - End-to-end CLI tests using `typer.testing.CliRunner`
- `test_error_handling.py` - Network failures, timeouts, malformed data
- `test_edge_cases.py` - Empty responses, missing fields, Unicode

---

### TEST-002: Add Playwright End-to-End Tests
**Status**: TODO (Blocked by infrastructure)  
**Priority**: Low  
**Effort**: 6+ hours  
**Impact**: Medium - Validates automation flows

**Description**:
Test Playwright automation against a mock alphaXiv server or use recorded sessions.

**Acceptance Criteria**:
- [ ] Login flow tested
- [ ] Overview generation tested
- [ ] Error scenarios covered (button not found, timeout)
- [ ] Tests run in CI

**Notes**: Requires mock server or Playwright test fixtures.

---

## Summary

| Priority | Count | Total Effort |
|----------|-------|--------------|
| High     | 3     | 4-6 hours    |
| Medium   | 5     | 6-8 hours    |
| Low      | 3     | 3-5 hours    |
| Testing  | 2     | 10-18 hours  |

**Total Estimated Effort**: 23-37 developer hours

**Recommended Implementation Order**:
1. SEC-001 + SEC-002 (Logging infrastructure + exception handling)
2. PERF-001 (Database batching)
3. TEST-001 (Increase coverage)
4. REFACTOR-001, REFACTOR-002, TYPE-001 (Code quality)
5. Remaining LOW priority tasks as time permits
