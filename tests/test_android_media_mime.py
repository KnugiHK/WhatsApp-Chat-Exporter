from mimetypes import MimeTypes

from Whatsapp_Chat_Exporter.android_handler import _process_single_media
from Whatsapp_Chat_Exporter.data_model import ChatCollection, ChatStore, Message
from Whatsapp_Chat_Exporter.utility import Device

CHAT_JID = "15550001111@s.whatsapp.net"


def _run(tmp_path, file_exists):
    (tmp_path / "Media").mkdir()
    if file_exists:
        (tmp_path / "Media" / "IMG-1.jpg").write_bytes(b"\xff\xd8\xff")
    data = ChatCollection()
    chat = data.add_chat(CHAT_JID, ChatStore(Device.ANDROID))
    chat.add_message(1, Message(from_me=False, timestamp=1700000000, time=1700000000, key_id="1"))
    content = {"file_path": "Media/IMG-1.jpg", "key_remote_jid": CHAT_JID, "message_row_id": 1,
               "mime_type": "image/jpeg", "thumbnail": None, "file_hash": None}
    _process_single_media(data, content, str(tmp_path), MimeTypes(), separate_media=False)
    return chat.get_message(1)


def test_missing_file_keeps_marker_and_recorded_type(tmp_path):
    message = _run(tmp_path, file_exists=False)
    assert message.mime == "media"
    assert message.data == "The media is missing"
    assert message.original_mime == "image/jpeg"


def test_existing_file(tmp_path):
    message = _run(tmp_path, file_exists=True)
    assert message.mime == "image/jpeg"
    assert message.original_mime == "image/jpeg"


def test_original_mime_survives_json_round_trip(tmp_path):
    message = _run(tmp_path, file_exists=False)
    assert Message.from_json(message.to_json()).original_mime == "image/jpeg"
