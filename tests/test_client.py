import pytest
import httpx
from client import AlphaXivClient, AlphaXivError


class MockTransport(httpx.MockTransport):
    def __init__(self, handler):
        super().__init__(handler)
        self.request_count = 0
    
    def handle_request(self, request):
        self.request_count += 1
        return self.handler(request)


def test_client_context_manager(tmp_path):
    with AlphaXivClient(cache_dir=str(tmp_path)) as client:
        assert client._http_client is not None
    
    with pytest.raises(RuntimeError, match="client has been closed"):
        client._http_client.get("https://test.com")


def test_client_retry_on_429(tmp_path):
    attempt = 0
    
    def handler(request):
        nonlocal attempt
        attempt += 1
        if attempt < 3:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json={"success": True})
    
    transport = MockTransport(handler)
    with AlphaXivClient(cache_dir=str(tmp_path)) as client:
        client._http_client = httpx.Client(transport=transport)
        
        response = client._request("GET", "https://api.test/papers/123")
        
        assert response.status_code == 200
        assert transport.request_count == 3


def test_client_raises_on_404(tmp_path):
    def handler(request):
        return httpx.Response(404, json={"error": "not found"})
    
    with AlphaXivClient(cache_dir=str(tmp_path)) as client:
        client._http_client = httpx.Client(transport=httpx.MockTransport(handler))
        
        with pytest.raises(AlphaXivError, match="API error: HTTP 404"):
            client._request("GET", "https://api.test/papers/invalid")


def test_client_cache_hit(tmp_path):
    request_count = 0
    
    def handler(request):
        nonlocal request_count
        request_count += 1
        return httpx.Response(200, json={"paper_id": "123"})
    
    with AlphaXivClient(cache_dir=str(tmp_path), cache_ttl=24) as client:
        client._http_client = httpx.Client(transport=httpx.MockTransport(handler))
        
        response1 = client._request("GET", "https://api.test/papers/123")
        response2 = client._request("GET", "https://api.test/papers/123")
        
        assert response1.json() == response2.json()
        assert request_count == 1


def test_client_cache_bypass_on_post(tmp_path):
    request_count = 0
    
    def handler(request):
        nonlocal request_count
        request_count += 1
        return httpx.Response(200, json={"result": "ok"})
    
    with AlphaXivClient(cache_dir=str(tmp_path)) as client:
        client._http_client = httpx.Client(transport=httpx.MockTransport(handler))
        
        client._request("POST", "https://api.test/generate", use_cache=False)
        client._request("POST", "https://api.test/generate", use_cache=False)
        
        assert request_count == 2


def test_resolve_paper(tmp_path):
    def handler(request):
        if "2204.04602" in str(request.url):
            return httpx.Response(200, json={
                "paper_id": "2204.04602",
                "title": "Test Paper",
                "versionId": "v1"
            })
        return httpx.Response(404)
    
    with AlphaXivClient(cache_dir=str(tmp_path)) as client:
        client._http_client = httpx.Client(transport=httpx.MockTransport(handler))
        
        result = client.resolve_paper("2204.04602")
        
        assert result is not None
        assert result["title"] == "Test Paper"
        assert result["versionId"] == "v1"


def test_get_overview(tmp_path):
    def handler(request):
        return httpx.Response(200, json={
            "overview": "This is an AI-generated overview",
            "summary": {"summary": "Brief summary"}
        })
    
    with AlphaXivClient(cache_dir=str(tmp_path)) as client:
        client._http_client = httpx.Client(transport=httpx.MockTransport(handler))
        
        result = client.get_overview("version-123")
        
        assert result["overview"] == "This is an AI-generated overview"
        assert result["summary"]["summary"] == "Brief summary"


def test_get_similar_papers(tmp_path):
    def handler(request):
        return httpx.Response(200, json=[
            {"paper_id": "1", "title": "Similar 1"},
            {"paper_id": "2", "title": "Similar 2"},
            {"paper_id": "3", "title": "Similar 3"},
        ])
    
    with AlphaXivClient(cache_dir=str(tmp_path)) as client:
        client._http_client = httpx.Client(transport=httpx.MockTransport(handler))
        
        result = client.get_similar_papers("2204.04602", limit=2)
        
        assert len(result) == 2
        assert result[0]["paper_id"] == "1"
