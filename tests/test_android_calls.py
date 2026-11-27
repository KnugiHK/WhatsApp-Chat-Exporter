import sqlite3

import pytest

from Whatsapp_Chat_Exporter.android_handler import (
    _call_log_tables_exist, _call_outcome, _construct_call_description,
    _get_messages_cursor_new, _process_single_message
)
from Whatsapp_Chat_Exporter.data_model import ChatCollection, Message, Timing

CONTACT_JID = "15550001111@s.whatsapp.net"

# Minimal modern (message table) schema with every table the message query joins
BASE_SCHEMA = """
    CREATE TABLE jid (_id INTEGER PRIMARY KEY, user TEXT, server TEXT, raw_string TEXT, type INTEGER);
    CREATE TABLE chat (_id INTEGER PRIMARY KEY, jid_row_id INTEGER, subject TEXT, hidden INTEGER DEFAULT 0);
    CREATE TABLE message (_id INTEGER PRIMARY KEY, chat_row_id INTEGER, from_me INTEGER, key_id TEXT,
        sender_jid_row_id INTEGER, status INTEGER, timestamp INTEGER, received_timestamp INTEGER,
        message_type INTEGER, text_data TEXT);
    CREATE TABLE message_quoted (message_row_id INTEGER, key_id TEXT, text_data TEXT);
    CREATE TABLE message_location (message_row_id INTEGER, latitude REAL, longitude REAL);
    CREATE TABLE message_media (message_row_id INTEGER, file_path TEXT);
    CREATE TABLE message_thumbnail (message_row_id INTEGER, thumbnail BLOB);
    CREATE TABLE message_future (message_row_id INTEGER, version INTEGER);
    CREATE TABLE missed_call_logs (message_row_id INTEGER, video_call INTEGER);
    CREATE TABLE message_system (message_row_id INTEGER, action_type INTEGER);
    CREATE TABLE message_system_group (message_row_id INTEGER, is_me_joined INTEGER);
    CREATE TABLE message_system_number_change (message_row_id INTEGER, old_jid_row_id INTEGER,
        new_jid_row_id INTEGER);
    CREATE TABLE receipt_user (message_row_id INTEGER, receipt_timestamp INTEGER, read_timestamp INTEGER,
        played_timestamp INTEGER);
    INSERT INTO jid VALUES (1, '15550001111', 's.whatsapp.net', '15550001111@s.whatsapp.net', 0);
    INSERT INTO chat VALUES (1, 1, NULL, 0);
"""

CALL_LOG_SCHEMA = """
    CREATE TABLE call_log (_id INTEGER PRIMARY KEY, video_call INTEGER, duration INTEGER,
        call_result INTEGER, bytes_transferred INTEGER);
    CREATE TABLE message_call_log (message_row_id INTEGER, call_log_row_id INTEGER);
"""


def _make_db(with_call_log=True):
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(BASE_SCHEMA + (CALL_LOG_SCHEMA if with_call_log else ""))
    return db


def _add_call_message(db, msg_id, from_me, video_call, call_result, duration, bytes_transferred):
    # In-chat call entries are metadata (status 6) messages of type 90
    db.execute("INSERT INTO message VALUES (?, 1, ?, ?, 0, 6, 1700000000000, 0, 90, NULL)",
               (msg_id, from_me, f"KEY{msg_id}"))
    if db.execute("SELECT count(*) FROM sqlite_master WHERE name='call_log'").fetchone()[0]:
        db.execute("INSERT INTO call_log VALUES (?, ?, ?, ?, ?)",
                   (msg_id, video_call, duration, call_result, bytes_transferred))
        db.execute("INSERT INTO message_call_log VALUES (?, ?)", (msg_id, msg_id))


def _export(db):
    data = ChatCollection()
    c = db.cursor()
    cursor = _get_messages_cursor_new(
        c, False, None, [None, None], "NULL AS transcription_text", False, _call_log_tables_exist(c))
    while (row := cursor.fetchone()) is not None:
        _process_single_message(data, row, True, Timing(0))
    return data.get_chat(CONTACT_JID)


@pytest.mark.parametrize("call_result, from_me, expected", [
    (0, True, "cancelled"),
    (0, False, "missed"),
    (2, True, "not answered"),
    (2, False, "missed"),
    (3, False, "unavailable"),
    (4, False, "missed"),
    (7, True, "cancelled"),
    (99, False, "in an unknown state"),
])
def test_call_outcome(call_result, from_me, expected):
    assert _call_outcome(call_result, from_me, 0, 0) == expected


def test_call_outcome_connected_call():
    assert _call_outcome(5, False, 65, 2048) == \
        "initiated and lasted for 1 minute 5 seconds with 2.0 KB data transferred"


def test_construct_call_description_unchanged():
    call = Message(from_me=False, timestamp=0, time=0, key_id="KEY", timezone_offset=Timing(0),
                   received_timestamp=None, read_timestamp=None)
    call.sender = "Alice"
    content = {"video_call": 1, "call_result": 2, "duration": 0, "bytes_transferred": 0}
    assert _construct_call_description(content, call) == "A video call from Alice was missed."


def test_call_log_tables_exist():
    assert _call_log_tables_exist(_make_db(with_call_log=True).cursor()) is True
    assert _call_log_tables_exist(_make_db(with_call_log=False).cursor()) is False


def test_in_chat_call_entries_are_described():
    db = _make_db()
    _add_call_message(db, 1, 0, 0, 2, 0, 0)          # incoming voice call, missed
    _add_call_message(db, 2, 1, 1, 2, 0, 0)          # outgoing video call, not answered
    _add_call_message(db, 3, 0, 0, 5, 125, 1048576)  # incoming voice call, connected
    chat = _export(db)

    assert chat.get_message(1).data == "A voice call was missed"
    assert chat.get_message(2).data == "A video call was not answered"
    assert chat.get_message(3).data == \
        "A voice call was initiated and lasted for 2 minutes 5 seconds with 1.0 MB data transferred"
    assert all(chat.get_message(i).meta for i in (1, 2, 3))


def test_call_entries_without_call_log_tables_still_export():
    db = _make_db(with_call_log=False)
    _add_call_message(db, 1, 0, 0, 2, 0, 0)
    chat = _export(db)

    # Falls back to the previous behaviour (no description) instead of failing
    assert chat.get_message(1).data is None
    assert chat.get_message(1).meta is True
