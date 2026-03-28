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
from sync_handlers import MacAppSyncHandler, create_sync_handler

FILE_SYNC_INFO_DDL = """
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
"""


def _create_file_sync_info_db(db_path, rows=None):
    """Helper: create an unencrypted DB with the file_sync_info schema."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(FILE_SYNC_INFO_DDL)
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


class TestMacAppUpdateModifiedFiles:
    """Tests for MacAppSyncHandler.update_modified_files()."""

    def test_updates_file_sync_info(self, tmp_path):
        """Should update last_size, last_md5, last_modified in file_sync_info."""
        db_path = tmp_path / "en_supernote.db"
        _create_file_sync_info_db(
            db_path,
            rows=[
                ("Note/test.note", 1000, 1000000000, "old_md5_hash", 1),
            ],
        )

        notes_base = tmp_path / "Supernote"
        note_dir = notes_base / "Note"
        note_dir.mkdir(parents=True)
        note_file = note_dir / "test.note"
        note_file.write_bytes(b"modified content here")

        handler = MacAppSyncHandler(database_path=db_path, notes_base_path=notes_base)
        updated, failed = handler.update_modified_files([note_file])

        assert updated == 1
        assert failed == 0

        # Verify the database was updated
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT last_size, last_md5, last_modified FROM file_sync_info WHERE path = 'Note/test.note'"
        ).fetchone()
        conn.close()

        assert row is not None
        expected_size = note_file.stat().st_size
        assert row[0] == expected_size
        assert row[1] is not None and row[1] != "old_md5_hash"
        assert row[2] is not None and row[2] != 1000000000

    def test_path_resolution(self, tmp_path):
        """Should convert absolute paths to relative paths matching file_sync_info."""
        db_path = tmp_path / "en_supernote.db"
        _create_file_sync_info_db(
            db_path,
            rows=[
                ("Note/deep/nested.note", 500, 1000000000, "old_hash", 1),
            ],
        )

        notes_base = tmp_path / "Supernote"
        note_dir = notes_base / "Note" / "deep"
        note_dir.mkdir(parents=True)
        note_file = note_dir / "nested.note"
        note_file.write_bytes(b"nested content")

        handler = MacAppSyncHandler(database_path=db_path, notes_base_path=notes_base)
        updated, failed = handler.update_modified_files([note_file])

        assert updated == 1
        assert failed == 0

    def test_fallback_to_filename_match(self, tmp_path):
        """Should fall back to filename matching when notes_base_path is not set."""
        db_path = tmp_path / "en_supernote.db"
        _create_file_sync_info_db(
            db_path,
            rows=[
                ("Note/somefile.note", 500, 1000000000, "old_hash", 1),
            ],
        )

        note_file = tmp_path / "somefile.note"
        note_file.write_bytes(b"content")

        handler = MacAppSyncHandler(database_path=db_path)  # no notes_base_path
        updated, failed = handler.update_modified_files([note_file])

        assert updated == 1
        assert failed == 0

    def test_file_not_in_database(self, tmp_path):
        """Should count as success when file is not tracked in database (new file)."""
        db_path = tmp_path / "en_supernote.db"
        _create_file_sync_info_db(db_path)  # empty

        note_file = tmp_path / "new.note"
        note_file.write_bytes(b"new content")

        handler = MacAppSyncHandler(database_path=db_path, notes_base_path=tmp_path)
        updated, failed = handler.update_modified_files([note_file])

        assert updated == 1
        assert failed == 0

    def test_missing_file(self, tmp_path):
        """Should count as failure when file no longer exists on disk."""
        db_path = tmp_path / "en_supernote.db"
        _create_file_sync_info_db(db_path)

        missing_file = tmp_path / "gone.note"

        handler = MacAppSyncHandler(database_path=db_path, notes_base_path=tmp_path)
        updated, failed = handler.update_modified_files([missing_file])

        assert updated == 0
        assert failed == 1

    def test_empty_list(self, tmp_path):
        """Should return 0,0 for empty file list."""
        db_path = tmp_path / "en_supernote.db"
        _create_file_sync_info_db(db_path)

        handler = MacAppSyncHandler(database_path=db_path)
        updated, failed = handler.update_modified_files([])

        assert updated == 0
        assert failed == 0


class TestCreateSyncHandler:
    """Tests for create_sync_handler() factory with db_key."""

    def test_mac_app_mode_passes_db_key(self, tmp_path):
        """Should pass db_key to MacAppSyncHandler."""
        db_path = tmp_path / "en_supernote.db"
        _create_file_sync_info_db(db_path)

        handler = create_sync_handler(
            mode="mac_app", mac_app_database=str(db_path), mac_app_db_key="test_key"
        )

        assert isinstance(handler, MacAppSyncHandler)
        assert handler.db_key == "test_key"

    def test_mac_app_mode_without_key(self, tmp_path):
        """Should work without a key (unencrypted database)."""
        db_path = tmp_path / "en_supernote.db"
        _create_file_sync_info_db(db_path)

        handler = create_sync_handler(mode="mac_app", mac_app_database=str(db_path))

        assert isinstance(handler, MacAppSyncHandler)
        assert handler.db_key is None

    def test_none_mode(self):
        """Should create NoOpSyncHandler for mode=none."""
        from sync_handlers import NoOpSyncHandler

        handler = create_sync_handler(mode="none")
        assert isinstance(handler, NoOpSyncHandler)


class TestMacAppIntegrationEncrypted:
    """Integration tests using an encrypted database (pysqlcipher3 required)."""

    def _create_encrypted_db(self, db_path, key, rows=None):
        """Create an encrypted database with file_sync_info schema."""
        from pysqlcipher3 import dbapi2 as sqlcipher

        conn = sqlcipher.connect(str(db_path))
        conn.execute(f'PRAGMA key = "{key}"')
        conn.execute(FILE_SYNC_INFO_DDL)
        if rows:
            for row in rows:
                conn.execute(
                    "INSERT INTO file_sync_info (path, last_size, last_modified, last_md5, is_file) VALUES (?, ?, ?, ?, ?)",
                    row,
                )
        conn.commit()
        conn.close()

    def _read_encrypted_db(self, db_path, key, query):
        """Read from encrypted database."""
        from pysqlcipher3 import dbapi2 as sqlcipher

        conn = sqlcipher.connect(str(db_path))
        conn.execute(f'PRAGMA key = "{key}"')
        result = conn.execute(query).fetchall()
        conn.close()
        return result

    def test_full_flow_encrypted(self, tmp_path):
        """End-to-end: encrypted DB → is_available → get_status → update_modified_files."""
        key = "integration_test_key"
        db_path = tmp_path / "en_supernote.db"

        # Create encrypted DB with one .note file tracked
        self._create_encrypted_db(
            db_path,
            key,
            rows=[
                ("Note/test.note", 100, 1000000000, "original_md5", 1),
                ("Note", 0, None, None, 0),
            ],
        )

        # Create the .note file on disk
        notes_base = tmp_path / "Supernote"
        note_dir = notes_base / "Note"
        note_dir.mkdir(parents=True)
        note_file = note_dir / "test.note"
        note_file.write_bytes(b"OCR-enhanced content goes here")

        handler = MacAppSyncHandler(
            database_path=db_path, notes_base_path=notes_base, db_key=key
        )

        # is_available
        assert handler.is_available() is True

        # get_status
        status = handler.get_status()
        assert status["note_files_tracked"] == 1

        # update_modified_files
        updated, failed = handler.update_modified_files([note_file])
        assert updated == 1
        assert failed == 0

        # Verify DB was updated through encryption
        rows = self._read_encrypted_db(
            db_path,
            key,
            "SELECT last_size, last_md5, last_modified FROM file_sync_info WHERE path = 'Note/test.note'",
        )
        assert len(rows) == 1
        assert rows[0][0] == note_file.stat().st_size
        assert rows[0][1] != "original_md5"
        assert rows[0][2] != 1000000000
