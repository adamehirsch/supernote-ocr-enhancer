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
