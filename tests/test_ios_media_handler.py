import sqlite3
from types import SimpleNamespace

from Whatsapp_Chat_Exporter.ios_media_handler import BackupExtractor


def test_extract_media_files_creates_nested_directories(tmp_path, monkeypatch):
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    with sqlite3.connect(backup_dir / "Manifest.db") as manifest:
        manifest.execute(
            "CREATE TABLE Files "
            "(fileID TEXT, domain TEXT, relativePath TEXT, "
            "flags INTEGER, file BLOB)"
        )
        manifest.execute(
            "INSERT INTO Files VALUES (?, ?, ?, ?, ?)",
            ("unused", "WhatsApp.shared", "parent/child", 2, None),
        )

    monkeypatch.chdir(tmp_path)
    identifiers = SimpleNamespace(DOMAIN="WhatsApp.shared")

    extractor = BackupExtractor(backup_dir, identifiers, decrypt_chunk_size=0)
    extractor._extract_media_files()

    assert (tmp_path / "WhatsApp.shared" / "parent" / "child").is_dir()
