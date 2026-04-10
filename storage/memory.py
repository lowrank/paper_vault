"""mempalace adapter for persistent semantic memory of arxiv papers."""
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _primary_category(info: dict) -> str:
    topics = info.get("topics", [])
    if topics:
        raw = topics[0] if isinstance(topics[0], str) else ""
        return raw.replace(".", "-")[:64] if raw else "general"
    return "general"


def upsert_paper(paper_id: str, info: dict, overview: dict, palace_path: Path) -> None:
    try:
        from mempalace.palace import get_collection
        text = overview.get("overview") or info.get("abstract", "")
        if not text:
            return
        room = _primary_category(info)
        col = get_collection(str(palace_path))
        col.upsert(
            ids=[paper_id],
            documents=[text],
            metadatas=[{
                "wing": "arxiv",
                "room": room,
                "title": info.get("title", ""),
                "arxiv_id": paper_id,
            }],
        )
    except Exception as e:
        logger.warning(f"mempalace upsert failed for {paper_id}: {e}")


def is_paper_known(paper_id: str, palace_path: Path) -> bool:
    try:
        from mempalace.palace import get_collection
        col = get_collection(str(palace_path))
        result = col.get(ids=[paper_id], include=[])
        return len(result.get("ids", [])) > 0
    except Exception as e:
        logger.warning(f"mempalace lookup failed for {paper_id}: {e}")
        return False


def add_citation_triple(from_id: str, to_id: str, kg_path: Path) -> None:
    try:
        from mempalace.knowledge_graph import KnowledgeGraph
        kg = KnowledgeGraph(str(kg_path))
        kg.add_triple(from_id, "cites", to_id)
    except Exception as e:
        logger.warning(f"KG add_triple failed ({from_id} -> {to_id}): {e}")


def add_topic_triple(paper_id: str, topic: str, kg_path: Path) -> None:
    try:
        from mempalace.knowledge_graph import KnowledgeGraph
        kg = KnowledgeGraph(str(kg_path))
        kg.add_triple(paper_id, "topic", topic)
    except Exception as e:
        logger.warning(f"KG topic triple failed ({paper_id} -> {topic}): {e}")


def search_papers(query: str, palace_path: Path, n: int = 5) -> list:
    try:
        from mempalace.searcher import search_memories
        return search_memories(query, palace_path=str(palace_path), wing="arxiv", n_results=n)
    except Exception as e:
        logger.warning(f"mempalace search failed: {e}")
        return []
