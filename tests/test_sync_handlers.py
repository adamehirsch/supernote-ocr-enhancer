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
from sync_handlers import MacAppSyncHandler


def _create_file_sync_info_db(db_path, rows=None):
    """Helper: create an unencrypted DB with the file_sync_info schema."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE "file_sync_info" (
            "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            "server_id" TEXT NULL,
            "path" TEXT NULL,
            "last_path" TEXT NULL,
            "delete_path" TEXT NULL,
            "last_size" INTEGER NULL,
            "last_modified" INTEGER NULL,
            "last_md5" TEXT NULL,
            "server_path" TEXT NULL,
            "event_time" INTEGER NOT NULL DEFAULT (CAST(strftime('%s', CURRENT_TIMESTAMP) AS INTEGER)),
            "event_type" TEXT NULL,
            "is_file" INTEGER NOT NULL DEFAULT 1,
            "is_sync" INTEGER NOT NULL DEFAULT 0,
            "cached_path" TEXT NULL,
            "sync_status" INTEGER NULL,
            UNIQUE ("path")
        )
    """)
    if rows:
        for row in rows:
            conn.execute(
                "INSERT INTO file_sync_info (path, last_size, last_modified, last_md5, is_file) VALUES (?, ?, ?, ?, ?)",
                row,
            )
    conn.commit()
    conn.close()


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


class TestMacAppConnect:
    """Tests for MacAppSyncHandler._connect() with and without encryption."""

    def test_connect_unencrypted(self, tmp_path):
        """Should connect to a plain SQLite database when no key is set."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.execute("INSERT INTO test VALUES (1)")
        conn.commit()
        conn.close()

        handler = MacAppSyncHandler(database_path=db_path)
        conn = handler._connect()
        try:
            rows = conn.execute("SELECT * FROM test").fetchall()
            assert rows == [(1,)]
        finally:
            conn.close()

    def test_connect_encrypted(self, tmp_path):
        """Should connect to an encrypted database when key is set."""
        from pysqlcipher3 import dbapi2 as sqlcipher

        db_path = tmp_path / "encrypted.db"
        key = "test_key_123"

        conn = sqlcipher.connect(str(db_path))
        conn.execute(f'PRAGMA key = "{key}"')
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.execute("INSERT INTO test VALUES (42)")
        conn.commit()
        conn.close()

        handler = MacAppSyncHandler(database_path=db_path, db_key=key)
        conn = handler._connect()
        try:
            rows = conn.execute("SELECT * FROM test").fetchall()
            assert rows == [(42,)]
        finally:
            conn.close()

    def test_connect_wrong_key_fails(self, tmp_path):
        """Should fail when the wrong key is provided."""
        from pysqlcipher3 import dbapi2 as sqlcipher
        import pytest

        db_path = tmp_path / "encrypted.db"

        conn = sqlcipher.connect(str(db_path))
        conn.execute('PRAGMA key = "correct_key"')
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.commit()
        conn.close()

        handler = MacAppSyncHandler(database_path=db_path, db_key="wrong_key")
        conn = handler._connect()
        with pytest.raises(Exception):
            conn.execute("SELECT * FROM test").fetchall()
        conn.close()

    def test_connect_no_key_on_encrypted_fails(self, tmp_path):
        """Should fail when no key is provided for an encrypted database."""
        from pysqlcipher3 import dbapi2 as sqlcipher
        import pytest

        db_path = tmp_path / "encrypted.db"

        conn = sqlcipher.connect(str(db_path))
        conn.execute('PRAGMA key = "some_key"')
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.commit()
        conn.close()

        handler = MacAppSyncHandler(database_path=db_path)
        conn = handler._connect()
        with pytest.raises(Exception):
            conn.execute("SELECT * FROM test").fetchall()
        conn.close()


class TestMacAppIsAvailable:
    """Tests for MacAppSyncHandler.is_available()."""

    def test_available_with_file_sync_info(self, tmp_path):
        """Should return True when file_sync_info table exists."""
        db_path = tmp_path / "en_supernote.db"
        _create_file_sync_info_db(db_path)

        handler = MacAppSyncHandler(database_path=db_path)
        assert handler.is_available() is True

    def test_unavailable_without_table(self, tmp_path):
        """Should return False when file_sync_info table doesn't exist."""
        db_path = tmp_path / "en_supernote.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE other_table (id INTEGER)")
        conn.commit()
        conn.close()

        handler = MacAppSyncHandler(database_path=db_path)
        assert handler.is_available() is False

    def test_unavailable_when_file_missing(self, tmp_path):
        """Should return False when database file doesn't exist."""
        handler = MacAppSyncHandler(database_path=tmp_path / "nonexistent.db")
        assert handler.is_available() is False


class TestMacAppGetStatus:
    """Tests for MacAppSyncHandler.get_status()."""

    def test_counts_note_files(self, tmp_path):
        """Should count only .note files (is_file=1)."""
        db_path = tmp_path / "en_supernote.db"
        _create_file_sync_info_db(
            db_path,
            rows=[
                ("Note/file1.note", 1000, 1234567890, "abc123", 1),
                ("Note/file2.note", 2000, 1234567891, "def456", 1),
                ("Note", 0, None, None, 0),  # directory, should not be counted
                ("SCREENSHOT/img.png", 500, 1234567892, "ghi789", 1),  # not .note
            ],
        )

        handler = MacAppSyncHandler(database_path=db_path)
        status = handler.get_status()

        assert status["mode"] == "mac_app"
        assert status["status"] == "available"
        assert status["note_files_tracked"] == 2

    def test_unavailable_status(self, tmp_path):
        """Should return unavailable when database is missing."""
        handler = MacAppSyncHandler(database_path=tmp_path / "nonexistent.db")
        status = handler.get_status()

        assert status["mode"] == "mac_app"
        assert status["status"] == "unavailable"
