"""Tests for sync_handlers module."""

import sys
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

# Add app directory to path so we can import sync_handlers
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from sync_handlers import auto_detect_mac_app_database, auto_detect_mac_app_path


class TestAutoDetectMacAppDatabase:
    """Tests for auto_detect_mac_app_database()."""

    def test_finds_en_supernote_db(self, tmp_path):
        """Should find en_supernote.db, not supernote.db."""
        # Create the directory structure the Mac app uses
        user_dir = tmp_path / "1194988350351380480"
        user_dir.mkdir()
        db_file = user_dir / "en_supernote.db"
        db_file.write_bytes(b"fake db")

        with patch("sync_handlers.auto_detect_mac_app_path", return_value=user_dir):
            result = auto_detect_mac_app_database()

        assert result == db_file

    def test_ignores_old_supernote_db(self, tmp_path):
        """Should NOT find the old supernote.db filename."""
        user_dir = tmp_path / "1194988350351380480"
        user_dir.mkdir()
        # Only create the old filename
        old_db = user_dir / "supernote.db"
        old_db.write_bytes(b"old db")

        with patch("sync_handlers.auto_detect_mac_app_path", return_value=user_dir):
            result = auto_detect_mac_app_database()

        assert result is None

    def test_returns_none_when_no_user_dir(self):
        """Should return None when no Mac app directory exists."""
        with patch("sync_handlers.auto_detect_mac_app_path", return_value=None):
            result = auto_detect_mac_app_database()

        assert result is None
