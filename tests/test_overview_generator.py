import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
from overview_generator import (
    load_credentials,
    check_login,
    login_to_alphaxiv,
    is_playwright_available
)


def test_load_credentials_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ALPHAXIV_EMAIL", "test@example.com")
    monkeypatch.setenv("ALPHAXIV_PASSWORD", "testpass123")
    
    email, password = load_credentials()
    
    assert email == "test@example.com"
    assert password == "testpass123"


def test_load_credentials_from_file(tmp_path, monkeypatch):
    monkeypatch.delenv("ALPHAXIV_EMAIL", raising=False)
    monkeypatch.delenv("ALPHAXIV_PASSWORD", raising=False)
    
    secret_file = tmp_path / "SECRET.md"
    secret_file.write_text("email: file@example.com\npassword: filepass456")
    
    import os
    import stat
    os.chmod(secret_file, stat.S_IRUSR | stat.S_IWUSR)
    
    email, password = load_credentials(secret_file)
    
    assert email == "file@example.com"
    assert password == "filepass456"


def test_load_credentials_refuses_insecure_permissions(tmp_path, monkeypatch):
    monkeypatch.delenv("ALPHAXIV_EMAIL", raising=False)
    monkeypatch.delenv("ALPHAXIV_PASSWORD", raising=False)
    
    secret_file = tmp_path / "SECRET.md"
    secret_file.write_text("email: test@example.com\npassword: pass123")
    
    import os
    import stat
    os.chmod(secret_file, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    
    email, password = load_credentials(secret_file)
    
    assert email is None
    assert password is None


def test_load_credentials_missing_file(tmp_path, monkeypatch):
    monkeypatch.delenv("ALPHAXIV_EMAIL", raising=False)
    monkeypatch.delenv("ALPHAXIV_PASSWORD", raising=False)
    
    secret_file = tmp_path / "nonexistent.md"
    
    email, password = load_credentials(secret_file)
    
    assert email is None
    assert password is None


def test_is_playwright_available():
    result = is_playwright_available()
    assert isinstance(result, bool)


@pytest.mark.skipif(not is_playwright_available(), reason="Playwright not installed")
def test_check_login_mocked():
    mock_page = Mock()
    mock_page.goto = Mock()
    mock_page.wait_for_timeout = Mock()
    
    mock_locator = Mock()
    mock_locator.is_visible = Mock(return_value=False)
    mock_locator.first = mock_locator
    
    mock_page.locator = Mock(return_value=mock_locator)
    
    result = check_login(mock_page)
    
    assert result is True
    mock_page.goto.assert_called_once()


@pytest.mark.skipif(not is_playwright_available(), reason="Playwright not installed")
def test_login_to_alphaxiv_mocked():
    mock_page = Mock()
    mock_page.goto = Mock()
    mock_page.wait_for_timeout = Mock()
    mock_page.keyboard.press = Mock()
    mock_page.url = "https://alphaxiv.org/home"
    
    mock_button = Mock()
    mock_button.click = Mock()
    mock_button.first = mock_button
    
    mock_input = Mock()
    mock_input.fill = Mock()
    mock_input.wait_for = Mock()
    mock_input.first = mock_input
    
    mock_page.locator = Mock(side_effect=[
        mock_button,
        mock_input,
        mock_input,
    ])
    
    result = login_to_alphaxiv(mock_page, "test@example.com", "pass123")
    
    assert result is True
    assert mock_button.click.call_count >= 1
