#!/usr/bin/env python3
"""AlphaXiv API Client."""

import httpx
import time
import hashlib
import asyncio
from typing import Optional, Dict, List, Any
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote as _urlquote


def _encode_id(paper_id: str) -> str:
    """
    URL-encode an arXiv paper or version ID for use as a URL path segment.

    Old-style IDs (pre-2007) contain a literal slash, e.g. 'math/0504536' or
    'hep-th/0305001'.  Interpolating them directly into an f-string URL turns
    that slash into a path separator, producing a 404.  Encoding it as %2F
    makes the whole ID a single path segment as intended.
    """
    return _urlquote(paper_id, safe="")

from alphaxiv_cli.storage.cache import Cache
from alphaxiv_cli.config import BASE_API_URL, USER_AGENT, DEFAULT_CACHE_DIR, DEFAULT_CACHE_TTL_HOURS, DEFAULT_TIMEOUT, DEFAULT_MAX_RETRIES


class AlphaXivError(Exception):
    """AlphaXiv API error."""
    pass


def _arxiv_result_to_dict(r) -> Dict[str, Any]:
    """Convert an arxiv.Result object to a plain dict matching our schema."""
    import re as _re
    # get_short_id() returns e.g. "2206.02262v4" — strip version suffix
    short_id = r.get_short_id()
    arxiv_id = _re.sub(r"v\d+$", "", short_id)
    return {
        "universal_paper_id": arxiv_id,
        "paper_id":           arxiv_id,
        "title":              r.title.strip().replace("\n", " "),
        "abstract":           r.summary.strip().replace("\n", " "),
        "authors":            [a.name for a in r.authors],
        "categories":         r.categories,
        "primary_category":   r.primary_category,
        "updated":            r.updated.strftime("%Y-%m-%d") if r.updated else "",
        "published":          r.published.strftime("%Y-%m-%d") if r.published else "",
        "comment":            (r.comment or "").strip(),
        "journal_ref":        (r.journal_ref or "").strip(),
        "doi":                (r.doi or "").strip(),
        "pdf_url":            r.pdf_url or "",
        "arxiv_url":          f"https://arxiv.org/abs/{arxiv_id}",
        "alphaxiv_url":       f"https://alphaxiv.org/abs/{arxiv_id}",
    }


class AlphaXivClient:
    """Client for interacting with alphaXiv API."""
    
    def __init__(self, timeout: float = DEFAULT_TIMEOUT, max_retries: int = DEFAULT_MAX_RETRIES, cache_dir: Optional[str] = None, cache_ttl: int = DEFAULT_CACHE_TTL_HOURS, api_key: Optional[str] = None):
        self.timeout = timeout
        self.max_retries = max_retries
        self._headers = {"User-Agent": USER_AGENT}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"
        self._cache = Cache(cache_dir=cache_dir or DEFAULT_CACHE_DIR, ttl_hours=cache_ttl)
        self._http_client = httpx.Client(timeout=self.timeout, headers=self._headers)
    
    def _cache_key(self, url: str, params: Optional[Dict] = None) -> str:
        """Generate cache key from URL and params."""
        key_str = url
        if params:
            key_str += "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def _request(self, method: str, url: str, use_cache: bool = True, **kwargs) -> httpx.Response:
        """Make HTTP request with retry logic and caching."""
        cache_key = None
        if use_cache and method.upper() == "GET":
            cache_key = self._cache_key(url, kwargs.get("params"))
            cached = self._cache.get(cache_key)
            if cached is not None:
                class CachedResponse:
                    def __init__(self, data):
                        self.status_code = 200
                        self._data = data
                    def json(self):
                        return self._data
                return CachedResponse(cached)
        
        for attempt in range(self.max_retries):
            try:
                response = self._http_client.request(method, url, **kwargs)
                
                if response.status_code >= 400:
                    if response.status_code == 429 and attempt < self.max_retries - 1:
                        wait_time = 2 ** attempt
                        time.sleep(wait_time)
                        continue
                    raise AlphaXivError(f"API error: HTTP {response.status_code} for {method} {url[:100]}")
                
                if use_cache and method.upper() == "GET" and cache_key:
                    try:
                        self._cache.set(cache_key, response.json())
                    except Exception:
                        pass
                
                return response
                
            except httpx.TimeoutException:
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise AlphaXivError(f"Request timeout after {self.max_retries} attempts")
            except httpx.RequestError as e:
                raise AlphaXivError(f"Request failed: {e}")
        
        raise AlphaXivError("Max retries exceeded")
    
    def resolve_paper(self, paper_id: str) -> Optional[Dict[str, Any]]:
        """Resolve arXiv ID to paper info."""
        url = f"{BASE_API_URL}/papers/v3/{_encode_id(paper_id)}"
        response = self._request("GET", url)
        
        if response.status_code == 404:
            return None
        
        return response.json()
    
    def get_overview(self, version_id: str, language: str = "en", use_cache: bool = True) -> Optional[Dict[str, Any]]:
        """Fetch paper overview (AI-generated summary)."""
        url = f"{BASE_API_URL}/papers/v3/{_encode_id(version_id)}/overview/{language}"
        response = self._request("GET", url, use_cache=use_cache)
        
        if response.status_code == 404:
            return None
        
        return response.json()
    
    def get_metrics(self, version_id: str) -> Optional[Dict[str, Any]]:
        """Fetch paper metrics."""
        url = f"{BASE_API_URL}/papers/v3/{_encode_id(version_id)}/metrics"
        response = self._request("GET", url)
        
        if response.status_code == 404:
            return None
        
        return response.json()
    
    def get_full_text(self, version_id: str) -> Optional[str]:
        """Fetch paper full text."""
        url = f"{BASE_API_URL}/papers/v3/{_encode_id(version_id)}/full-text"
        response = self._request("GET", url)
        
        if response.status_code == 404:
            return None
        
        data = response.json()
        if isinstance(data, dict):
            full_text = data.get("fullText", {})
            if isinstance(full_text, dict):
                return full_text.get("text", "")
            return str(full_text)
        return str(data)
    
    def get_similar_papers(self, paper_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetch similar papers."""
        url = f"{BASE_API_URL}/papers/v3/{_encode_id(paper_id)}/similar-papers"
        response = self._request("GET", url)
        
        if response.status_code == 404:
            return []
        
        papers = response.json()
        return papers[:limit] if isinstance(papers, list) else []
    
    def get_citations(self, paper_id: str) -> List[Dict[str, Any]]:
        """Fetch paper citations."""
        url = f"{BASE_API_URL}/papers/v3/{_encode_id(paper_id)}/citations"
        response = self._request("GET", url)
        
        if response.status_code == 404:
            return []
        
        return response.json()
    
    def get_references(self, paper_id: str) -> List[Dict[str, Any]]:
        """Fetch paper references."""
        url = f"{BASE_API_URL}/papers/v3/{_encode_id(paper_id)}/references"
        response = self._request("GET", url)
        
        if response.status_code == 404:
            return []
        
        return response.json()
    
    def search(self, query: str, limit: int = 20, sort_by: str = "relevance") -> List[Dict[str, Any]]:
        """
        Search arXiv papers via the arxiv.py library (lukasschwab/arxiv.py).

        The alphaxiv search endpoint (/papers/v3/search) returns 404 for all
        queries; this implementation uses the official arXiv API wrapper instead.

        query syntax:
          plain text        — title + abstract full-text search
          ti:word           — title only
          au:name           — author name
          cat:cs.LG         — category filter
          ti:X AND cat:cs.LG — boolean combination

        sort_by: "relevance" | "lastUpdatedDate" | "submittedDate"
        """
        import arxiv

        _SORT_MAP = {
            "relevance":       arxiv.SortCriterion.Relevance,
            "lastupdateddate": arxiv.SortCriterion.LastUpdatedDate,
            "submitteddate":   arxiv.SortCriterion.SubmittedDate,
        }
        sort_criterion = _SORT_MAP.get(sort_by.lower(), arxiv.SortCriterion.Relevance)

        cache_key = self._cache_key(f"arxiv:search:{sort_by}", {"q": query, "n": limit})
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            search = arxiv.Search(
                query=query,
                max_results=limit,
                sort_by=sort_criterion,
                sort_order=arxiv.SortOrder.Descending,
            )
            client = arxiv.Client(
                page_size=min(limit, 100),
                delay_seconds=1.0,
                num_retries=self.max_retries,
            )
            raw_results = list(client.results(search))
        except Exception as e:
            raise AlphaXivError(f"arXiv search failed: {e}")

        results = [_arxiv_result_to_dict(r) for r in raw_results]
        self._cache.set(cache_key, results)
        return results
    
    def get_similar_papers_batch(self, paper_ids: List[str], limit: int = 10, max_workers: int = 5) -> Dict[str, List[Dict[str, Any]]]:
        """Fetch similar papers for multiple papers in parallel."""
        results = {}
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_id = {
                executor.submit(self.get_similar_papers, pid, limit): pid
                for pid in paper_ids
            }
            
            for future in as_completed(future_to_id):
                paper_id = future_to_id[future]
                try:
                    results[paper_id] = future.result()
                except Exception as e:
                    results[paper_id] = []
        
        return results
    
    def get_overviews_batch(self, version_ids: List[str], language: str = "en", max_workers: int = 5) -> Dict[str, Optional[Dict[str, Any]]]:
        """Fetch overviews for multiple papers in parallel."""
        results = {}
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_id = {
                executor.submit(self.get_overview, vid, language): vid
                for vid in version_ids
            }
            
            for future in as_completed(future_to_id):
                version_id = future_to_id[future]
                try:
                    results[version_id] = future.result()
                except Exception:
                    results[version_id] = None
        
        return results
    
    def get_overview_status(self, version_id: str) -> Optional[Dict[str, Any]]:
        """Check overview generation status without fetching the full overview."""
        url = f"{BASE_API_URL}/papers/v3/{_encode_id(version_id)}/overview/status"
        response = self._request("GET", url)
        
        if response.status_code == 404:
            return None
        
        return response.json()
    
    def get_resources(self, version_id: str) -> Optional[Dict[str, Any]]:
        """Fetch paper resources (implementations, datasets, etc.)."""
        url = f"{BASE_API_URL}/papers/v3/{_encode_id(version_id)}/resources"
        response = self._request("GET", url)
        
        if response.status_code == 404:
            return None
        
        return response.json()
    
    def request_ai_overview(self, paper_id: str, version_order: int = 1, language: str = "en") -> Optional[Dict[str, Any]]:
        """Request AI overview generation for a paper."""
        url = f"{BASE_API_URL}/papers/v3/{_encode_id(paper_id)}/overview/request"
        data = {
            "versionOrder": version_order,
            "language": language
        }
        response = self._request("POST", url, json=data, use_cache=False)
        
        if response.status_code >= 400:
            return None
        
        return response.json()
    
    def close(self):
        """Close HTTP client and release connections."""
        self._http_client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()


def get_client() -> AlphaXivClient:
    """Get configured AlphaXivClient instance."""
    return AlphaXivClient()
