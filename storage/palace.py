"""
Research Palace — a mempalace-inspired structured memory store for academic papers.

Hierarchy mirrors the Memory Palace metaphor:

  WING   → a research session / topic (e.g. "diffusion-models-2024")
  HALL   → memory type corridor, same across every wing:
             hall_facts        — established results, proven theorems, key numbers
             hall_discoveries  — new ideas surfaced while reading
             hall_questions    — open questions / gaps the reader found
             hall_methods      — techniques, architectures, algorithms
             hall_context      — background / related-work summaries
  ROOM   → individual paper (e.g. "2310.06825")
  CLOSET → distilled per-paper summary pointing into the drawers
  DRAWER → verbatim text: abstract, overview sections, citation snippets

All structured data lives in a single SQLite file (research_palace.sqlite3).
Semantic retrieval uses ChromaDB (same backend as the existing `memory.py`
utils, but with richer wing/hall/room metadata so filters are much more
precise than the flat "arxiv" wing used there).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HALLS = (
    "hall_facts",
    "hall_discoveries",
    "hall_questions",
    "hall_methods",
    "hall_context",
)

_HALL_DISPLAY = {
    "hall_facts":       "Established Facts & Results",
    "hall_discoveries": "Discoveries & Insights",
    "hall_questions":   "Open Questions & Gaps",
    "hall_methods":     "Methods & Architectures",
    "hall_context":     "Background & Related Work",
}

# ---------------------------------------------------------------------------
# SQLite persistence helpers
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS wings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT UNIQUE NOT NULL,
    topic       TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rooms (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    wing_name   TEXT NOT NULL,
    paper_id    TEXT NOT NULL,
    title       TEXT NOT NULL,
    hall        TEXT NOT NULL,
    added_at    TEXT NOT NULL,
    UNIQUE(wing_name, paper_id, hall)
);

CREATE TABLE IF NOT EXISTS drawers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    wing_name   TEXT NOT NULL,
    paper_id    TEXT NOT NULL,
    hall        TEXT NOT NULL,
    label       TEXT NOT NULL,
    content     TEXT NOT NULL,
    stored_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS closets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    wing_name   TEXT NOT NULL,
    paper_id    TEXT NOT NULL,
    summary     TEXT NOT NULL,
    keywords    TEXT NOT NULL,     -- JSON list
    updated_at  TEXT NOT NULL,
    UNIQUE(wing_name, paper_id)
);

CREATE TABLE IF NOT EXISTS tunnels (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    from_wing   TEXT NOT NULL,
    from_paper  TEXT NOT NULL,
    to_wing     TEXT NOT NULL,
    to_paper    TEXT NOT NULL,
    relation    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE(from_wing, from_paper, to_wing, to_paper, relation)
);

CREATE TABLE IF NOT EXISTS synthesis (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    wing_name   TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

-- Obsidian note paths generated asynchronously by `axiv research link`
CREATE TABLE IF NOT EXISTS note_links (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    wing_name   TEXT NOT NULL,
    paper_id    TEXT NOT NULL,
    note_path   TEXT NOT NULL,        -- absolute path to .md note
    report_path TEXT,                  -- absolute path to _report.md (may be NULL)
    linked_at   TEXT NOT NULL,
    UNIQUE(wing_name, paper_id)
);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Wing operations
# ---------------------------------------------------------------------------

def create_wing(wing_name: str, topic: str, db_path: Path) -> None:
    """Create a research wing (session) if it doesn't already exist."""
    try:
        conn = _connect(db_path)
        conn.execute(
            "INSERT OR IGNORE INTO wings (name, topic, created_at) VALUES (?,?,?)",
            (wing_name, topic, _now()),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"create_wing failed: {e}")


def list_wings(db_path: Path) -> list[dict]:
    try:
        conn = _connect(db_path)
        rows = conn.execute(
            "SELECT w.name, w.topic, w.created_at, COUNT(DISTINCT r.paper_id) AS paper_count "
            "FROM wings w LEFT JOIN rooms r ON r.wing_name = w.name "
            "GROUP BY w.name ORDER BY w.created_at DESC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"list_wings failed: {e}")
        return []


def get_wing(wing_name: str, db_path: Path) -> Optional[dict]:
    try:
        conn = _connect(db_path)
        row = conn.execute(
            "SELECT * FROM wings WHERE name=?", (wing_name,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        logger.warning(f"get_wing failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Room & drawer operations
# ---------------------------------------------------------------------------

def add_paper_to_wing(
    wing_name: str,
    paper_id: str,
    title: str,
    info: dict,
    overview: Optional[dict],
    db_path: Path,
) -> None:
    """
    Place a paper into the wing by:
      1. Creating rooms in each relevant hall.
      2. Storing verbatim content in drawers.
      3. Building a distilled closet summary.
    """
    try:
        conn = _connect(db_path)
        now = _now()

        abstract = info.get("abstract", "")
        full_overview = (overview or {}).get("overview", "")
        summary_text = ""
        if isinstance((overview or {}).get("summary"), dict):
            summary_text = overview["summary"].get("summary", "")
        citations = (overview or {}).get("citations", [])
        topics = info.get("topics", [])

        # --- classify into halls ---
        hall_content: dict[str, list[tuple[str, str]]] = {h: [] for h in HALLS}

        # hall_context  → abstract + background section of overview
        if abstract:
            hall_content["hall_context"].append(("abstract", abstract))
        if summary_text:
            hall_content["hall_context"].append(("ai_summary", summary_text))

        # hall_facts → structured facts extracted from aiTooltips / key sentences
        ai_tooltips = (overview or {}).get("aiTooltips", [])
        for tip in (ai_tooltips or []):
            if isinstance(tip, dict):
                name = tip.get("name", "")
                explanation = tip.get("explanation", "")
                if name and explanation:
                    hall_content["hall_facts"].append((f"fact:{name}", explanation))

        # hall_methods → algorithm / architecture keywords from topics + title
        for t in topics[:5]:
            if isinstance(t, str) and t:
                hall_content["hall_methods"].append(("topic", t))
        # also first 600 chars of full overview as method context
        if full_overview:
            hall_content["hall_methods"].append((
                "overview_excerpt",
                full_overview[:2000],
            ))

        # hall_facts  → key citation summaries
        for c in citations[:5]:
            if isinstance(c, dict):
                ctitle = c.get("title", "")
                cjust  = c.get("justification", "")
                if ctitle and cjust:
                    hall_content["hall_facts"].append((
                        f"citation:{ctitle[:50]}",
                        cjust,
                    ))

        # hall_discoveries & hall_questions → full overview (LLM will surface these
        # when querying; we store the full text here for completeness)
        if full_overview:
            hall_content["hall_discoveries"].append(("full_overview", full_overview))
            # Questions: extract sentences ending in "?"
            questions = _extract_questions(full_overview)
            for i, q in enumerate(questions[:10]):
                hall_content["hall_questions"].append((f"q{i}", q))

        # Persist rooms + drawers
        for hall, items in hall_content.items():
            if not items:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO rooms (wing_name, paper_id, title, hall, added_at) "
                "VALUES (?,?,?,?,?)",
                (wing_name, paper_id, title, hall, now),
            )
            for label, content in items:
                conn.execute(
                    "INSERT INTO drawers (wing_name, paper_id, hall, label, content, stored_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (wing_name, paper_id, hall, label, content, now),
                )

        # Closet summary (distilled map of what's in all drawers)
        keywords = [t for t in topics if isinstance(t, str)][:8]
        closet_summary = _build_closet(title, abstract, summary_text, keywords)
        conn.execute(
            "INSERT OR REPLACE INTO closets (wing_name, paper_id, summary, keywords, updated_at) "
            "VALUES (?,?,?,?,?)",
            (wing_name, paper_id, closet_summary, json.dumps(keywords), now),
        )

        conn.commit()
        conn.close()

    except Exception as e:
        logger.warning(f"add_paper_to_wing failed for {paper_id}: {e}")


def _extract_questions(text: str) -> list[str]:
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in sentences if s.strip().endswith("?")]


def _build_closet(title: str, abstract: str, summary: str, keywords: list) -> str:
    """Compact distilled summary pointing into the drawers."""
    kw_str = ", ".join(keywords[:6]) if keywords else "N/A"
    body = summary if summary else abstract
    if abstract and abstract[:400] not in (summary or ""):
        body = f"{body} | {abstract}"
    return f"[{title}] topics={kw_str} | {body}"


# ---------------------------------------------------------------------------
# Tunnel (cross-paper connection)
# ---------------------------------------------------------------------------

def add_tunnel(
    from_wing: str,
    from_paper: str,
    to_wing: str,
    to_paper: str,
    relation: str,
    db_path: Path,
) -> None:
    """Connect two rooms across wings (or within the same wing)."""
    try:
        conn = _connect(db_path)
        conn.execute(
            "INSERT OR IGNORE INTO tunnels (from_wing, from_paper, to_wing, to_paper, relation, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (from_wing, from_paper, to_wing, to_paper, relation, _now()),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"add_tunnel failed: {e}")


def get_tunnels(wing_name: str, paper_id: str, db_path: Path) -> list[dict]:
    try:
        conn = _connect(db_path)
        rows = conn.execute(
            "SELECT * FROM tunnels WHERE (from_wing=? AND from_paper=?) "
            "OR (to_wing=? AND to_paper=?)",
            (wing_name, paper_id, wing_name, paper_id),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"get_tunnels failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Semantic search via ChromaDB
# ---------------------------------------------------------------------------

def upsert_to_chroma(
    wing_name: str,
    paper_id: str,
    info: dict,
    overview: Optional[dict],
    palace_path: Path,
) -> None:
    """Store paper in ChromaDB with rich wing/hall/room metadata for filtered search."""
    try:
        from alphaxiv_cli.client import extract_overview_text
        from mempalace.palace import get_collection  # type: ignore

        text = extract_overview_text(overview) or info.get("abstract", "")
        if not text:
            return

        topics = info.get("topics", [])
        room = topics[0].replace(".", "-")[:64] if topics else "general"

        col = get_collection(str(palace_path))
        col.upsert(
            ids=[f"{wing_name}::{paper_id}"],
            documents=[text],
            metadatas=[{
                "wing":     wing_name,
                "hall":     "hall_context",
                "room":     room,
                "paper_id": paper_id,
                "title":    info.get("title", ""),
            }],
        )
    except Exception as e:
        logger.warning(f"upsert_to_chroma failed for {paper_id}: {e}")


def search_palace(
    query: str,
    wing_name: Optional[str],
    hall: Optional[str],
    palace_path: Path,
    n: int = 10,
) -> list[dict]:
    """
    Semantic search with optional wing/hall filters.
    Returns list of {paper_id, title, wing, hall, document, distance} dicts.

    Queries the ChromaDB collection directly so we can use our own metadata
    schema (wing, hall, paper_id, title) rather than mempalace's schema.
    """
    try:
        from mempalace.palace import get_collection  # type: ignore

        col = get_collection(str(palace_path))
        if col.count() == 0:
            return []

        where: dict = {}
        if wing_name and hall:
            where = {"$and": [{"wing": {"$eq": wing_name}}, {"hall": {"$eq": hall}}]}
        elif wing_name:
            where = {"wing": {"$eq": wing_name}}
        elif hall:
            where = {"hall": {"$eq": hall}}

        kwargs: dict = {
            "query_texts": [query],
            "n_results": min(n, col.count()),
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        results = col.query(**kwargs)
        hits = []
        docs   = results["documents"][0]
        metas  = results["metadatas"][0]
        dists  = results["distances"][0]
        for doc, meta, dist in zip(docs, metas, dists):
            hits.append({
                "paper_id": meta.get("paper_id", "?"),
                "title":    meta.get("title", ""),
                "wing":     meta.get("wing", ""),
                "hall":     meta.get("hall", ""),
                "document": doc,
                "distance": round(float(dist), 4),
            })
        return hits
    except Exception as e:
        logger.warning(f"search_palace failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Wing-level synthesis storage
# ---------------------------------------------------------------------------

def save_synthesis(wing_name: str, content: str, db_path: Path) -> None:
    try:
        conn = _connect(db_path)
        conn.execute(
            "INSERT INTO synthesis (wing_name, content, created_at) VALUES (?,?,?)",
            (wing_name, content, _now()),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"save_synthesis failed: {e}")


def get_syntheses(wing_name: str, db_path: Path) -> list[dict]:
    try:
        conn = _connect(db_path)
        rows = conn.execute(
            "SELECT * FROM synthesis WHERE wing_name=? ORDER BY created_at DESC",
            (wing_name,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"get_syntheses failed: {e}")
        return []


def clear_syntheses(wing_name: str, db_path: Path, keep_latest: bool = False) -> int:
    """Delete synthesis versions for a wing. Returns count deleted."""
    try:
        conn = _connect(db_path)
        if keep_latest:
            cur = conn.execute("""
                DELETE FROM synthesis WHERE wing_name=? AND id NOT IN (
                    SELECT id FROM synthesis WHERE wing_name=? ORDER BY created_at DESC LIMIT 1
                )
            """, (wing_name, wing_name))
        else:
            cur = conn.execute("DELETE FROM synthesis WHERE wing_name=?", (wing_name,))
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        return deleted
    except Exception as e:
        logger.warning(f"clear_syntheses failed: {e}")
        return 0


# ---------------------------------------------------------------------------
# Wing status / closet navigation
# ---------------------------------------------------------------------------

def wing_status(wing_name: str, db_path: Path) -> dict:
    """Return a structured overview of a wing: halls, room counts, closet summaries."""
    try:
        conn = _connect(db_path)

        wing_row = conn.execute(
            "SELECT * FROM wings WHERE name=?", (wing_name,)
        ).fetchone()
        if not wing_row:
            conn.close()
            return {}

        result: dict = dict(wing_row)
        result["halls"] = {}
        result["closets"] = []

        for hall in HALLS:
            rooms = conn.execute(
                "SELECT DISTINCT paper_id, title FROM rooms WHERE wing_name=? AND hall=?",
                (wing_name, hall),
            ).fetchall()
            result["halls"][hall] = {
                "display": _HALL_DISPLAY[hall],
                "papers":  [dict(r) for r in rooms],
            }

        closets = conn.execute(
            "SELECT paper_id, summary, keywords FROM closets WHERE wing_name=? ORDER BY updated_at",
            (wing_name,),
        ).fetchall()
        for row in closets:
            kws = json.loads(row["keywords"]) if row["keywords"] else []
            result["closets"].append({
                "paper_id": row["paper_id"],
                "summary":  row["summary"],
                "keywords": kws,
            })

        tunnels = conn.execute(
            "SELECT * FROM tunnels WHERE from_wing=? OR to_wing=?",
            (wing_name, wing_name),
        ).fetchall()
        result["tunnel_count"] = len(tunnels)

        syntheses = conn.execute(
            "SELECT COUNT(*) as n FROM synthesis WHERE wing_name=?",
            (wing_name,),
        ).fetchone()
        result["synthesis_count"] = syntheses["n"] if syntheses else 0

        conn.close()
        return result

    except Exception as e:
        logger.warning(f"wing_status failed: {e}")
        return {}


def get_hall_drawers(wing_name: str, hall: str, db_path: Path) -> list[dict]:
    """Retrieve all drawers for a specific hall in a wing."""
    try:
        conn = _connect(db_path)
        rows = conn.execute(
            "SELECT paper_id, label, content, stored_at FROM drawers "
            "WHERE wing_name=? AND hall=? ORDER BY paper_id, label",
            (wing_name, hall),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"get_hall_drawers failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Note-link operations  (Obsidian note paths stored asynchronously)
# ---------------------------------------------------------------------------

def set_note_link(
    wing_name: str,
    paper_id: str,
    note_path: Path,
    report_path: Optional[Path],
    db_path: Path,
) -> None:
    """Record the Obsidian note (and optional report) path for a room."""
    try:
        conn = _connect(db_path)
        conn.execute(
            "INSERT OR REPLACE INTO note_links "
            "(wing_name, paper_id, note_path, report_path, linked_at) "
            "VALUES (?,?,?,?,?)",
            (
                wing_name,
                paper_id,
                str(note_path),
                str(report_path) if report_path else None,
                _now(),
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"set_note_link failed for {paper_id}: {e}")


def get_note_link(wing_name: str, paper_id: str, db_path: Path) -> Optional[dict]:
    """Return {note_path, report_path, linked_at} or None."""
    try:
        conn = _connect(db_path)
        row = conn.execute(
            "SELECT note_path, report_path, linked_at FROM note_links "
            "WHERE wing_name=? AND paper_id=?",
            (wing_name, paper_id),
        ).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        logger.warning(f"get_note_link failed for {paper_id}: {e}")
        return None


def get_all_note_links(wing_name: str, db_path: Path) -> dict[str, dict]:
    """Return {paper_id: {note_path, report_path, linked_at}} for the whole wing."""
    try:
        conn = _connect(db_path)
        rows = conn.execute(
            "SELECT paper_id, note_path, report_path, linked_at FROM note_links "
            "WHERE wing_name=?",
            (wing_name,),
        ).fetchall()
        conn.close()
        return {r["paper_id"]: dict(r) for r in rows}
    except Exception as e:
        logger.warning(f"get_all_note_links failed: {e}")
        return {}


def get_room(wing_name: str, paper_id: str, db_path: Path) -> Optional[dict]:
    """
    Return everything known about one paper-room:
      title, closet summary, keywords, all drawers grouped by hall, note link.
    """
    try:
        conn = _connect(db_path)

        # title from first room row
        room_row = conn.execute(
            "SELECT title FROM rooms WHERE wing_name=? AND paper_id=? LIMIT 1",
            (wing_name, paper_id),
        ).fetchone()
        if not room_row:
            conn.close()
            return None

        closet = conn.execute(
            "SELECT summary, keywords FROM closets WHERE wing_name=? AND paper_id=?",
            (wing_name, paper_id),
        ).fetchone()

        drawers = conn.execute(
            "SELECT hall, label, content FROM drawers "
            "WHERE wing_name=? AND paper_id=? ORDER BY hall, label",
            (wing_name, paper_id),
        ).fetchall()

        tunnels = conn.execute(
            "SELECT from_paper, to_paper, relation FROM tunnels "
            "WHERE (from_wing=? AND from_paper=?) OR (to_wing=? AND to_paper=?)",
            (wing_name, paper_id, wing_name, paper_id),
        ).fetchall()

        note_link = conn.execute(
            "SELECT note_path, report_path, linked_at FROM note_links "
            "WHERE wing_name=? AND paper_id=?",
            (wing_name, paper_id),
        ).fetchone()

        conn.close()

        # Group drawers by hall
        by_hall: dict[str, list[dict]] = {h: [] for h in HALLS}
        for d in drawers:
            if d["hall"] in by_hall:
                by_hall[d["hall"]].append({"label": d["label"], "content": d["content"]})

        kws = json.loads(closet["keywords"]) if closet and closet["keywords"] else []

        return {
            "paper_id":   paper_id,
            "title":      room_row["title"],
            "summary":    closet["summary"] if closet else "",
            "keywords":   kws,
            "halls":      by_hall,
            "tunnels":    [dict(t) for t in tunnels],
            "note_path":  note_link["note_path"]   if note_link else None,
            "report_path": note_link["report_path"] if note_link else None,
            "linked_at":  note_link["linked_at"]   if note_link else None,
        }
    except Exception as e:
        logger.warning(f"get_room failed for {paper_id}: {e}")
        return None


def list_rooms(wing_name: str, db_path: Path) -> list[dict]:
    """Return distinct papers in a wing with their closet summary and note-link status."""
    try:
        conn = _connect(db_path)
        rows = conn.execute(
            "SELECT DISTINCT r.paper_id, r.title, r.added_at, "
            "  c.summary, c.keywords, "
            "  n.note_path, n.report_path "
            "FROM rooms r "
            "LEFT JOIN closets c ON c.wing_name=r.wing_name AND c.paper_id=r.paper_id "
            "LEFT JOIN note_links n ON n.wing_name=r.wing_name AND n.paper_id=r.paper_id "
            "WHERE r.wing_name=? "
            "ORDER BY r.id ASC",
            (wing_name,),
        ).fetchall()
        conn.close()
        result = []
        for row in rows:
            kws = json.loads(row["keywords"]) if row["keywords"] else []
            result.append({
                "paper_id":   row["paper_id"],
                "title":      row["title"],
                "added_at":   row["added_at"],
                "summary":    row["summary"] or "",
                "keywords":   kws,
                "note_path":  row["note_path"],
                "report_path": row["report_path"],
            })
        return result
    except Exception as e:
        logger.warning(f"list_rooms failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Paper removal
# ---------------------------------------------------------------------------

def remove_paper_from_wing(wing_name: str, paper_id: str, db_path: Path) -> bool:
    """
    Remove a paper and all associated data from a wing.

    Deletes from: rooms, drawers, closets, tunnels.
    Note links (and the underlying note/report files on disk) are
    intentionally preserved so the user keeps the generated overview
    and report even after trimming the paper.
    Returns True if any rows were deleted, False otherwise.
    """
    try:
        conn = _connect(db_path)
        total = 0
        for table, clause in [
            ("rooms",      "wing_name=? AND paper_id=?"),
            ("drawers",    "wing_name=? AND paper_id=?"),
            ("closets",    "wing_name=? AND paper_id=?"),
        ]:
            cur = conn.execute(f"DELETE FROM {table} WHERE {clause}", (wing_name, paper_id))
            total += cur.rowcount

        # Tunnels reference from/to — remove both directions
        cur = conn.execute(
            "DELETE FROM tunnels WHERE "
            "(from_wing=? AND from_paper=?) OR (to_wing=? AND to_paper=?)",
            (wing_name, paper_id, wing_name, paper_id),
        )
        total += cur.rowcount

        conn.commit()
        conn.close()
        return total > 0
    except Exception as e:
        logger.warning(f"remove_paper_from_wing failed for {paper_id}: {e}")
        return False


def remove_paper_from_chroma(wing_name: str, paper_id: str, palace_path: Path) -> bool:
    """Remove a paper's ChromaDB entry from the palace collection."""
    try:
        from mempalace.palace import get_collection  # type: ignore
        col = get_collection(str(palace_path))
        doc_id = f"{wing_name}::{paper_id}"
        # Check if the ID exists before attempting deletion
        existing = col.get(ids=[doc_id])
        if existing and existing["ids"]:
            col.delete(ids=[doc_id])
            return True
        return False
    except Exception as e:
        logger.warning(f"remove_paper_from_chroma failed for {paper_id}: {e}")
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
