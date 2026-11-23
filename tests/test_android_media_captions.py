import mimetypes
from pathlib import Path

from Whatsapp_Chat_Exporter.android_handler import _process_single_media
from Whatsapp_Chat_Exporter.data_model import ChatCollection, ChatStore, Message


def _setup_store(jid: str, msg_id: int, msg_type: int, data_text: str | None, caption: str | None = None, meta: bool = False):
    store = ChatCollection()
    chat = ChatStore("android", "Test Chat")
    store.add_chat(jid, chat)
    msg = Message(
        from_me=True,
        timestamp=1700000000,
        time="12:00",
        key_id=f"key_{msg_id}",
        message_type=msg_type,
    )
    msg.data = data_text
    msg.caption = caption
    msg.meta = meta
    chat.add_message(msg_id, msg)
    return store, msg


def test_video_and_document_keep_caption_even_when_media_present(tmp_path: Path):
    media_dir = tmp_path / "Media"
    media_dir.mkdir()
    (media_dir / "video.mp4").write_bytes(b"mp4")
    (media_dir / "doc.pdf").write_bytes(b"pdf")

    store, video_msg = _setup_store("123@s.whatsapp.net", 1, 3, "Line 1 <br>Line 2")
    _process_single_media(
        store,
        {
            "key_remote_jid": "123@s.whatsapp.net",
            "message_row_id": 1,
            "file_path": "video.mp4",
            "mime_type": "video/mp4",
            "thumbnail": None,
            "file_hash": None,
        },
        str(media_dir),
        mimetypes.MimeTypes(),
        False,
    )
    assert video_msg.caption == "Line 1\nLine 2"
    assert video_msg.data.endswith("video.mp4")

    store2, doc_msg = _setup_store("123@s.whatsapp.net", 2, 9, "Report PDF")
    _process_single_media(
        store2,
        {
            "key_remote_jid": "123@s.whatsapp.net",
            "message_row_id": 2,
            "file_path": "doc.pdf",
            "mime_type": "application/pdf",
            "thumbnail": None,
            "file_hash": None,
        },
        str(media_dir),
        mimetypes.MimeTypes(),
        False,
    )
    assert doc_msg.caption == "Report PDF"


def test_missing_media_keeps_caption_and_skips_audio_sticker_meta(tmp_path: Path):
    media_dir = tmp_path / "Media"
    media_dir.mkdir()

    # Missing document keeps caption
    store, doc_msg = _setup_store("123@s.whatsapp.net", 1, 9, "Missing doc caption")
    _process_single_media(
        store,
        {
            "key_remote_jid": "123@s.whatsapp.net",
            "message_row_id": 1,
            "file_path": "missing.pdf",
            "mime_type": None,
            "thumbnail": None,
            "file_hash": None,
        },
        str(media_dir),
        mimetypes.MimeTypes(),
        False,
    )
    assert doc_msg.caption == "Missing doc caption"

    # Audio (2), sticker (20), meta messages keep caption as None
    for idx, (mtype, meta) in enumerate([(2, False), (20, False), (3, True)], start=2):
        s, m = _setup_store("123@s.whatsapp.net", idx, mtype, "ignored", meta=meta)
        _process_single_media(
            s,
            {
                "key_remote_jid": "123@s.whatsapp.net",
                "message_row_id": idx,
                "file_path": "missing.bin",
                "mime_type": None,
                "thumbnail": None,
                "file_hash": None,
            },
            str(media_dir),
            mimetypes.MimeTypes(),
            False,
        )
        assert m.caption is None
