import mimetypes
from pathlib import Path

from Whatsapp_Chat_Exporter.android_handler import _process_single_media, _to_html_media_path
from Whatsapp_Chat_Exporter.data_model import ChatCollection, ChatStore, Message


def test_to_html_media_path_converts_absolute_windows_and_relative_paths():
    assert _to_html_media_path(r"D:\Backups\WhatsApp\separated\Alice\img.jpg", r"D:\Backups\WhatsApp") == (
        "WhatsApp/separated/Alice/img.jpg"
    )
    assert _to_html_media_path(r"WhatsApp\separated\Alice\img.jpg", "WhatsApp") == (
        "WhatsApp/separated/Alice/img.jpg"
    )


def test_process_single_media_uses_relative_posix_paths_with_abs_media_folder(tmp_path: Path):
    media_dir = tmp_path / "WhatsApp"
    (media_dir / "Media").mkdir(parents=True)
    (media_dir / "Media" / "IMG.jpg").write_bytes(b"jpg")

    store = ChatCollection()
    chat = ChatStore("android", "Alice")
    msg = Message(from_me=True, timestamp=1700000000, time="12:00", key_id="k1", message_type=1)
    chat.add_message(1, msg)
    store.add_chat("123@s.whatsapp.net", chat)

    _process_single_media(
        store,
        {
            "key_remote_jid": "123@s.whatsapp.net",
            "message_row_id": 1,
            "file_path": "Media/IMG.jpg",
            "mime_type": "image/jpeg",
            "thumbnail": None,
            "file_hash": None,
        },
        str(media_dir.resolve()),
        mimetypes.MimeTypes(),
        True,
    )

    assert msg.data == "WhatsApp/separated/Alice/IMG.jpg"
    assert "\\" not in msg.data
    assert not Path(msg.data).is_absolute()
