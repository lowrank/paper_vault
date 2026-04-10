import pytest
import json
import time
from pathlib import Path
from storage.cache import Cache


def test_cache_basic_get_set(tmp_path):
    cache = Cache(cache_dir=str(tmp_path), ttl_hours=24)
    
    cache.set("test_key", {"foo": "bar"})
    result = cache.get("test_key")
    
    assert result == {"foo": "bar"}


def test_cache_miss_returns_none(tmp_path):
    cache = Cache(cache_dir=str(tmp_path), ttl_hours=24)
    
    result = cache.get("nonexistent_key")
    
    assert result is None


def test_cache_expiry(tmp_path):
    cache = Cache(cache_dir=str(tmp_path), ttl_hours=0.0001)
    
    cache.set("expiring_key", {"data": "value"})
    time.sleep(0.5)
    result = cache.get("expiring_key")
    
    assert result is None


def test_cache_corrupted_json_returns_none(tmp_path):
    cache_dir = tmp_path / ".alphaxiv_cache"
    cache_dir.mkdir()
    
    cache_file = cache_dir / "corrupted.json"
    cache_file.write_text("{ invalid json }")
    
    cache = Cache(cache_dir=str(tmp_path), ttl_hours=24)
    result = cache.get("corrupted")
    
    assert result is None


def test_cache_file_created_with_correct_structure(tmp_path):
    cache = Cache(cache_dir=str(tmp_path), ttl_hours=24)
    
    cache.set("struct_test", {"key": "value"})
    
    cache_files = list(tmp_path.glob("*.json"))
    assert len(cache_files) == 1
    
    data = json.loads(cache_files[0].read_text())
    assert "cached_at" in data
    assert "value" in data
    assert data["value"] == {"key": "value"}


def test_cache_multiple_keys(tmp_path):
    cache = Cache(cache_dir=str(tmp_path), ttl_hours=24)
    
    cache.set("key1", {"data": "one"})
    cache.set("key2", {"data": "two"})
    cache.set("key3", {"data": "three"})
    
    assert cache.get("key1") == {"data": "one"}
    assert cache.get("key2") == {"data": "two"}
    assert cache.get("key3") == {"data": "three"}


def test_cache_overwrite_existing_key(tmp_path):
    cache = Cache(cache_dir=str(tmp_path), ttl_hours=24)
    
    cache.set("overwrite", {"version": 1})
    cache.set("overwrite", {"version": 2})
    
    result = cache.get("overwrite")
    assert result == {"version": 2}
