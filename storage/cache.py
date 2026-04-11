"""Storage utilities - Caching and database."""
import json
import logging
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


class Cache:
    """Simple file-based cache for API responses."""
    
    def __init__(self, cache_dir: str = ".alphaxiv_cache", ttl_hours: int = 24):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl = timedelta(hours=ttl_hours)
    
    def _get_cache_path(self, key: str) -> Path:
        key_hash = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / f"{key_hash}.json"
    
    def get(self, key: str) -> Optional[Any]:
        """Get cached value if not expired."""
        cache_path = self._get_cache_path(key)
        if not cache_path.exists():
            return None
        
        try:
            data = json.loads(cache_path.read_text())
            cached_at = datetime.fromisoformat(data['cached_at'])
            # Ensure timezone-aware comparison (legacy entries may be naive)
            if cached_at.tzinfo is None:
                cached_at = cached_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - cached_at > self.ttl:
                cache_path.unlink()
                return None
            
            return data['value']
        except json.JSONDecodeError as e:
            logger.warning(f"Corrupted cache file {cache_path}, removing: {e}")
            try:
                cache_path.unlink()
            except OSError:
                pass
            return None
        except (KeyError, ValueError) as e:
            logger.warning(f"Invalid cache data in {cache_path}: {e}")
            return None
        except OSError as e:
            logger.warning(f"Failed to read cache file {cache_path}: {e}")
            return None
    
    def set(self, key: str, value: Any):
        """Cache a value."""
        cache_path = self._get_cache_path(key)
        data = {
            'cached_at': datetime.now(timezone.utc).isoformat(),
            'value': value
        }
        cache_path.write_text(json.dumps(data))
    
    def clear(self):
        """Clear all cached data."""
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink()


class PaperDatabase:
    """Track processed papers and metadata."""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db = self._load()
    
    def _load(self) -> Dict[str, Any]:
        if self.db_path.exists():
            return json.loads(self.db_path.read_text())
        return {}
    
    def save(self):
        """Persist database to disk."""
        self.db_path.write_text(json.dumps(self.db, indent=2))
    
    def has(self, paper_id: str) -> bool:
        """Check if paper already processed."""
        return paper_id in self.db
    
    def add(self, paper_id: str, metadata: Dict[str, Any]):
        """Add paper to database."""
        self.db[paper_id] = {
            **metadata,
            'processed_at': datetime.now(timezone.utc).isoformat()
        }
        self.save()
    
    def get(self, paper_id: str) -> Optional[Dict[str, Any]]:
        """Get paper metadata."""
        return self.db.get(paper_id)
    
    def count(self) -> int:
        """Total papers in database."""
        return len(self.db)
    
    def stats(self) -> Dict[str, Any]:
        """Database statistics."""
        return {
            'total': len(self.db),
            'by_date': self._count_by_date()
        }
    
    def _count_by_date(self) -> Dict[str, int]:
        counts = {}
        for data in self.db.values():
            date = data.get('date', 'unknown')
            counts[date] = counts.get(date, 0) + 1
        return counts
