"""
Project context — resolves all workspace paths for a research session.

Resolution order
----------------
1. Walk from CWD upward looking for a `.axiv` marker file.
   If found, that directory is the **project root** and all paths are
   relative to it.
2. If no `.axiv` file is found anywhere, fall back to the global store
   at `~/.alphaxiv/`.

The `.axiv` file is a JSON file written by `axiv init`.  It may contain
path overrides for individual locations (notes_dir, etc.); anything not
specified falls back to defaults relative to the project root.

Typical layout after `axiv init`:
  <project>/
    .axiv                  ← marker + config
    palace.sqlite3         ← research palace DB
    palace/                ← ChromaDB vector store
    knowledge_graph.sqlite3
    notes/                 ← Obsidian markdown notes
    reports/               ← per-paper report notes
    cache/                 ← HTTP response cache
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Name of the marker file that identifies a project root
MARKER = ".axiv"

# Global fallback root (used when no .axiv is found)
GLOBAL_ROOT = Path.home() / ".alphaxiv"


# ---------------------------------------------------------------------------
# ProjectContext dataclass
# ---------------------------------------------------------------------------

@dataclass
class ProjectContext:
    """All resolved paths for one research workspace."""

    root: Path                   # project root (dir containing .axiv, or GLOBAL_ROOT)
    is_local: bool               # True when rooted in CWD ancestry, False = global

    # Derived paths (all absolute)
    palace_db:  Path = field(init=False)
    palace_dir: Path = field(init=False)
    kg_db:      Path = field(init=False)
    notes_dir:  Path = field(init=False)
    reports_dir: Path = field(init=False)
    cache_dir:  Path = field(init=False)

    # Overrides read from .axiv
    _overrides: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        ov = self._overrides
        self.palace_db   = self._resolve(ov.get("palace_db"),   "palace.sqlite3")
        self.palace_dir  = self._resolve(ov.get("palace_dir"),  "palace")
        self.kg_db       = self._resolve(ov.get("kg_db"),       "knowledge_graph.sqlite3")
        self.notes_dir   = self._resolve(ov.get("notes_dir"),   "notes")
        self.reports_dir = self._resolve(ov.get("reports_dir"), "reports")
        self.cache_dir   = self._resolve(ov.get("cache_dir"),   "cache")

    def _resolve(self, override: Optional[str], default_name: str) -> Path:
        if override:
            p = Path(override)
            return p if p.is_absolute() else (self.root / p)
        return self.root / default_name

    @property
    def marker_path(self) -> Path:
        return self.root / MARKER

    def describe(self) -> str:
        scope = f"local ({self.root})" if self.is_local else f"global ({self.root})"
        return scope


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _find_marker(start: Path) -> Optional[Path]:
    """Walk upward from `start` looking for a .axiv marker file."""
    current = start.resolve()
    while True:
        candidate = current / MARKER
        if candidate.is_file():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def get_context(cwd: Optional[Path] = None) -> ProjectContext:
    """
    Return the ProjectContext for the given directory (defaults to CWD).

    Walks upward looking for a .axiv file.  Falls back to the global store.
    """
    start = Path(cwd) if cwd else Path.cwd()
    project_root = _find_marker(start)

    if project_root is not None:
        overrides = _read_overrides(project_root / MARKER)
        return ProjectContext(root=project_root, is_local=True, _overrides=overrides)

    # Global fallback
    overrides = _read_overrides(GLOBAL_ROOT / MARKER)
    return ProjectContext(root=GLOBAL_ROOT, is_local=False, _overrides=overrides)


def _read_overrides(marker: Path) -> dict:
    if not marker.is_file():
        return {}
    try:
        data = json.loads(marker.read_text())
        return data.get("paths", {})
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

def init_project(
    directory: Path,
    notes_dir: Optional[str] = None,
    reports_dir: Optional[str] = None,
    force: bool = False,
) -> ProjectContext:
    """
    Write a .axiv marker into `directory` and return the resulting context.
    Raises FileExistsError if a .axiv already exists and force=False.
    """
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)

    marker = directory / MARKER
    if marker.is_file() and not force:
        raise FileExistsError(
            f".axiv already exists at {marker}. Use --force to reinitialise."
        )

    paths: dict = {}
    if notes_dir:
        paths["notes_dir"] = notes_dir
    if reports_dir:
        paths["reports_dir"] = reports_dir

    config = {"version": 1, "paths": paths}
    marker.write_text(json.dumps(config, indent=2))

    return get_context(directory)
