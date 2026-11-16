import plistlib
import sqlite3
from pathlib import Path

from Whatsapp_Chat_Exporter.ios_media_handler import BackupExtractor
from Whatsapp_Chat_Exporter.utility import WhatsAppIdentifier


def _bplist_metadata() -> bytes:
    return plistlib.dumps(
        {
            "$objects": [
                "$null",
                {"Birth": 1700000000, "LastModified": 1700000000},
            ]
        },
        fmt=plistlib.FMT_BINARY,
    )


def test_extract_media_replaces_stale_file_blocking_manifest_directory(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    identifiers = WhatsAppIdentifier
    base_dir = tmp_path / "backup"
    file_id = "ab1234567890"
    (base_dir / "ab").mkdir(parents=True)
    (base_dir / "ab" / file_id).write_bytes(b"img-bytes")

    manifest = sqlite3.connect(base_dir / "Manifest.db")
    manifest.execute(
        "CREATE TABLE Files (fileID TEXT, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)"
    )
    meta = _bplist_metadata()
    manifest.execute(
        "INSERT INTO Files VALUES (?, ?, ?, ?, ?)",
        ("dir0000000", identifiers.DOMAIN, "a", 2, meta),
    )
    manifest.execute(
        "INSERT INTO Files VALUES (?, ?, ?, ?, ?)",
        (file_id, identifiers.DOMAIN, "a/x.jpg", 1, meta),
    )
    manifest.commit()
    manifest.close()

    # Pre-existing regular file sitting where Manifest.db lists directory "a"
    domain_dir = tmp_path / identifiers.DOMAIN
    domain_dir.mkdir()
    (domain_dir / "a").write_text("stale file", encoding="utf-8")

    extractor = BackupExtractor(str(base_dir), identifiers, 1024)
    extractor._extract_media_files()

    extracted = domain_dir / "a" / "x.jpg"
    assert (domain_dir / "a").is_dir()
    assert extracted.is_file()
    assert extracted.read_bytes() == b"img-bytes"
