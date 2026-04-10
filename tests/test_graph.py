import pytest
from pathlib import Path
from commands.graph import sanitize_paper_id


def test_sanitize_paper_id_valid_arxiv_id():
    result = sanitize_paper_id("2204.04602")
    assert result == "2204.04602"


def test_sanitize_paper_id_removes_slashes():
    result = sanitize_paper_id("../../etc/passwd")
    assert "/" not in result
    assert "_" in result


def test_sanitize_paper_id_removes_special_chars():
    result = sanitize_paper_id("paper<>:\"?*|id")
    assert "<" not in result
    assert ">" not in result
    assert ":" not in result
    assert '"' not in result
    assert "?" not in result
    assert "*" not in result
    assert "|" not in result


def test_sanitize_paper_id_preserves_allowed_chars():
    result = sanitize_paper_id("paper-2024.05.v2")
    assert result == "paper-2024.05.v2"


def test_sanitize_paper_id_truncates_long_names():
    long_id = "a" * 300
    result = sanitize_paper_id(long_id)
    assert len(result) == 255


def test_sanitize_paper_id_empty_string():
    result = sanitize_paper_id("")
    assert result == ""


def test_sanitize_paper_id_all_invalid_chars():
    result = sanitize_paper_id("///:::**")
    assert result == "________"
