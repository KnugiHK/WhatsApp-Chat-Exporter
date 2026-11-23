from types import SimpleNamespace
from pathlib import Path

from Whatsapp_Chat_Exporter.__main__ import handle_media_directory


def test_separated_media_copies_only_referenced_subdirs(tmp_path: Path):
    media_dir = tmp_path / "WhatsApp"
    (media_dir / "Media" / "WhatsApp Images").mkdir(parents=True)
    (media_dir / "Media" / "WhatsApp Images" / "raw.jpg").write_bytes(b"raw")
    (media_dir / "separated" / "Alice").mkdir(parents=True)
    (media_dir / "separated" / "Alice" / "img.jpg").write_bytes(b"sep")
    (media_dir / "thumbnails").mkdir(parents=True)
    (media_dir / "thumbnails" / "t.png").write_bytes(b"thumb")
    (media_dir / "vCards").mkdir(parents=True)
    (media_dir / "vCards" / "a.vcf").write_text("BEGIN:VCARD", encoding="utf-8")

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    args = SimpleNamespace(
        media=str(media_dir),
        output=str(out_dir),
        separate_media=True,
        move_media=False,
    )
    handle_media_directory(args)

    assert (out_dir / "WhatsApp" / "separated" / "Alice" / "img.jpg").is_file()
    assert (out_dir / "WhatsApp" / "thumbnails" / "t.png").is_file()
    assert (out_dir / "WhatsApp" / "vCards" / "a.vcf").is_file()
    assert not (out_dir / "WhatsApp" / "Media" / "WhatsApp Images" / "raw.jpg").exists()
