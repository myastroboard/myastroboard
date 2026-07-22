"""
Unit tests for txtconf_loader.py
"""
from unittest.mock import patch, mock_open

from utils.txtconf_loader import get_repo_version


class TestGetRepoVersion:
    """Tests for get_repo_version."""

    def test_returns_string(self):
        assert isinstance(get_repo_version(), str)

    def test_returns_non_empty_string(self):
        assert len(get_repo_version()) > 0

    def test_reads_version_file_content(self):
        with patch("builtins.open", mock_open(read_data="4.2.0")):
            assert get_repo_version() == "4.2.0"

    def test_strips_whitespace(self):
        with patch("builtins.open", mock_open(read_data="  3.1.0\n")):
            assert get_repo_version() == "3.1.0"

    def test_file_missing_returns_default(self):
        with patch("builtins.open", side_effect=FileNotFoundError("not found")):
            assert get_repo_version() == "1.0.0"

    def test_generic_exception_returns_default(self):
        with patch("builtins.open", side_effect=OSError("permission denied")):
            assert get_repo_version() == "1.0.0"
