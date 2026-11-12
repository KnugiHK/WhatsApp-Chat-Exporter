import logging
from types import SimpleNamespace
from Whatsapp_Chat_Exporter.__main__ import handle_media_directory


def test_handle_media_directory_trailing_slash_on_media_path(tmp_path):
    """os.path.basename('D:\\...\\WhatsApp\\') returns '' unless normalized first."""
    source = tmp_path / "source" / "WhatsApp"
    output = tmp_path / "output"
    source.mkdir(parents=True)
    (source / "photo.jpg").write_text("media")
    output.mkdir()

    # Trailing slash often breaks naive os.path.basename() fixes
    args = SimpleNamespace(
        media=str(source) + "/",
        output=str(output),
        move_media=False,
    )

    handle_media_directory(args)

    assert (output / "WhatsApp" / "photo.jpg").read_text() == "media"


def test_handle_media_directory_relative_media_path(tmp_path, monkeypatch):
    """Ensure relative -m paths (e.g., -m 'WhatsApp') still work as before."""
    source = tmp_path / "WhatsApp"
    output = tmp_path / "output"
    source.mkdir()
    (source / "photo.jpg").write_text("media")
    output.mkdir()

    monkeypatch.chdir(tmp_path)
    args = SimpleNamespace(
        media="WhatsApp",
        output=str(output),
        move_media=False,
    )

    handle_media_directory(args)

    assert (output / "WhatsApp" / "photo.jpg").read_text() == "media"


def test_handle_media_directory_skips_when_destination_actually_exists(tmp_path, caplog):
    """Verify the skip logic still triggers when <output>/WhatsApp genuinely exists."""
    source = tmp_path / "source" / "WhatsApp"
    output = tmp_path / "output"
    existing_dest = output / "WhatsApp"

    source.mkdir(parents=True)
    (source / "photo.jpg").write_text("new_media")
    existing_dest.mkdir(parents=True)
    (existing_dest / "photo.jpg").write_text("old_media")

    args = SimpleNamespace(
        media=str(source),
        output=str(output),
        move_media=False,
    )

    with caplog.at_level(logging.INFO):
        handle_media_directory(args)

    assert "already exists in output directory" in caplog.text
    assert (existing_dest / "photo.jpg").read_text() == "old_media"


def test_handle_media_directory_moves_absolute_media_path(tmp_path):
    """Verify move_media=True moves the folder and removes the source."""
    source = tmp_path / "source" / "WhatsApp"
    output = tmp_path / "output"
    source.mkdir(parents=True)
    (source / "photo.jpg").write_text("media")
    output.mkdir()

    args = SimpleNamespace(
        media=str(source),
        output=str(output),
        move_media=True,
    )

    handle_media_directory(args)

    assert (output / "WhatsApp" / "photo.jpg").read_text() == "media"
    assert not source.exists()