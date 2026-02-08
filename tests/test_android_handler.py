import sqlite3

import pytest

from Whatsapp_Chat_Exporter import android_handler
from Whatsapp_Chat_Exporter.data_model import ChatCollection, ChatStore, Message
from Whatsapp_Chat_Exporter.utility import Device


VCARD_CONTENT = "BEGIN:VCARD\nFN:Test User\nEND:VCARD"


def _row_from_select(sql, params=()):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur.fetchone()


def test_process_vcard_row_positive(tmp_path):
    # Prepare an sqlite row that contains all expected columns
    key_remote_jid = "12345@s.whatsapp.net"
    message_row_id = 42
    media_name = "Test vCard"

    sql = (
        "SELECT ? as message_row_id, ? as key_remote_jid, ? as vcard, ? as media_name"
    )
    row = _row_from_select(sql, (message_row_id, key_remote_jid, VCARD_CONTENT, media_name))

    # Prepare data model with a chat and a message
    data = ChatCollection()
    chat = ChatStore(Device.ANDROID, "Test Chat")
    msg = Message(from_me=True, timestamp=1600000000, time=1600000000, key_id=1)
    chat.add_message(message_row_id, msg)
    data.add_chat(key_remote_jid, chat)

    outdir = tmp_path / "vcards"
    outdir.mkdir()

    # Call the function under test
    android_handler._process_vcard_row(row, str(outdir), data)

    # Assert file created
    expected_file = outdir / ("".join(x for x in media_name if x.isalnum()) + ".vcf")
    assert expected_file.exists()

    # Assert message updated
    updated = data.get_chat(key_remote_jid).get_message(message_row_id)
    assert updated is not None
    assert updated.mime == "text/x-vcard"
    assert updated.meta is True
    assert updated.safe is True
    assert media_name in updated.data


def test_process_vcard_row_no_key_remote_jid(tmp_path):
    # key_remote_jid is NULL in the returned sqlite row
    sql = "SELECT 1 as message_row_id, NULL as key_remote_jid, ? as vcard, ? as media_name"
    row = _row_from_select(sql, (VCARD_CONTENT, "NoJid"))

    data = ChatCollection()
    outdir = tmp_path / "vcards2"
    outdir.mkdir()

    # Should write the file but not raise; no chat exists for None
    android_handler._process_vcard_row(row, str(outdir), data)

    expected_file = outdir / ("".join(x for x in "NoJid" if x.isalnum()) + ".vcf")
    assert expected_file.exists()
    # No chat added
    assert len(data) == 0


def test_process_vcard_row_missing_message_row_id(tmp_path):
    # Provide a row without message_row_id column (simulate older/strange schema)
    sql = "SELECT ? as key_remote_jid, ? as vcard, ? as media_name"
    key_remote_jid = "99999@s.whatsapp.net"
    row = _row_from_select(sql, (key_remote_jid, VCARD_CONTENT, "MissingId"))

    data = ChatCollection()
    chat = ChatStore(Device.ANDROID, "Chat MissingId")
    # No messages in the chat
    data.add_chat(key_remote_jid, chat)

    outdir = tmp_path / "vcards3"
    outdir.mkdir()

    # Call should write file but return early when message_row_id is missing
    android_handler._process_vcard_row(row, str(outdir), data)

    expected_file = outdir / ("".join(x for x in "MissingId" if x.isalnum()) + ".vcf")
    assert expected_file.exists()
    # Chat should still have no messages
    chat_obj = data.get_chat(key_remote_jid)
    assert isinstance(chat_obj, ChatStore)
    # ChatStore exposes message keys via .keys(); ensure it's empty
    assert list(chat_obj.keys()) == []


class _FakeRow:
    def __init__(self, mapping, exc_for_message_id=None):
        self._mapping = mapping
        self._exc = exc_for_message_id

    def __getitem__(self, key):
        if key == "message_row_id" and self._exc is not None:
            raise self._exc
        return self._mapping.get(key)


def test_process_vcard_row_handles_known_exceptions(tmp_path):
    # Simulate sqlite row that raises KeyError (a "good" exception)
    mapping = {
        "media_name": "GoodEx",
        "vcard": VCARD_CONTENT,
        "key_remote_jid": "ke@g.jid"
    }
    row = _FakeRow(mapping, exc_for_message_id=KeyError("missing"))

    data = ChatCollection()
    # Add a chat but no messages: function should return quietly
    data.add_chat(mapping["key_remote_jid"], ChatStore(Device.ANDROID, "Ch"))

    outdir = tmp_path / "vcards_good"
    outdir.mkdir()

    # Should not raise
    android_handler._process_vcard_row(row, str(outdir), data)

    expected_file = outdir / ("".join(x for x in "GoodEx" if x.isalnum()) + ".vcf")
    assert expected_file.exists()


def test_process_vcard_row_propagates_runtime_error(tmp_path):
    # Simulate sqlite row that raises an unexpected RuntimeError
    mapping = {
        "media_name": "BadEx",
        "vcard": VCARD_CONTENT,
        "key_remote_jid": "bad@jid"
    }
    row = _FakeRow(mapping, exc_for_message_id=RuntimeError("boom"))

    data = ChatCollection()
    data.add_chat(mapping["key_remote_jid"], ChatStore(Device.ANDROID, "Ch2"))

    outdir = tmp_path / "vcards_bad"
    outdir.mkdir()

    with pytest.raises(RuntimeError):
        android_handler._process_vcard_row(row, str(outdir), data)

    expected_file = outdir / ("".join(x for x in "BadEx" if x.isalnum()) + ".vcf")
    # file is written before the exception is raised
    assert expected_file.exists()
