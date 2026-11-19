import sqlite3
from pathlib import Path

from Whatsapp_Chat_Exporter.android_handler import vcard
from Whatsapp_Chat_Exporter.data_model import ChatCollection, ChatStore, Message


def _create_vcard_db(with_jid_map: bool) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE jid (_id INTEGER PRIMARY KEY, raw_string TEXT);
        CREATE TABLE chat (_id INTEGER PRIMARY KEY, jid_row_id INTEGER, hidden INTEGER DEFAULT 0);
        CREATE TABLE message (
            _id INTEGER PRIMARY KEY,
            chat_row_id INTEGER,
            sender_jid_row_id INTEGER,
            timestamp INTEGER,
            text_data TEXT,
            broadcast INTEGER DEFAULT 0
        );
        CREATE TABLE message_vcard (message_row_id INTEGER, vcard TEXT);
        """
    )
    if with_jid_map:
        conn.execute("CREATE TABLE jid_map (lid_row_id INTEGER, jid_row_id INTEGER);")
    return conn


def test_vcard_resolves_lid_via_jid_map(tmp_path: Path):
    conn = _create_vcard_db(with_jid_map=True)
    conn.execute("INSERT INTO jid VALUES (1, '12345@s.whatsapp.net'), (2, '99999@lid'), (3, 'unmapped@lid')")
    conn.execute("INSERT INTO jid_map VALUES (2, 1)")
    conn.execute("INSERT INTO chat VALUES (10, 2, 0), (11, 3, 0)")
    conn.execute("INSERT INTO message VALUES (100, 10, NULL, 1700000000000, 'Alice', 0)")
    conn.execute("INSERT INTO message VALUES (101, 11, NULL, 1700000001000, 'Ghost', 0)")
    conn.execute("INSERT INTO message_vcard VALUES (100, 'BEGIN:VCARD\\nFN:Alice\\nEND:VCARD')")
    conn.execute("INSERT INTO message_vcard VALUES (101, 'BEGIN:VCARD\\nFN:Ghost\\nEND:VCARD')")

    store = ChatCollection()
    store.set_system("jid_map_exists", True)
    chat = ChatStore("android", "Alice")
    msg = Message(from_me=True, timestamp=1700000000, time="12:00", key_id="k1")
    chat.add_message(100, msg)
    store.add_chat("12345@s.whatsapp.net", chat)

    media_dir = tmp_path / "Media"
    media_dir.mkdir()
    vcard(conn, store, str(media_dir), None, ([], []), True)

    assert msg.mime == "text/x-vcard"
    assert "Alice.vcf" in str(msg.data)
    assert (media_dir / "vCards" / "Alice.vcf").is_file()


def test_vcard_without_jid_map_still_works(tmp_path: Path):
    conn = _create_vcard_db(with_jid_map=False)
    conn.execute("INSERT INTO jid VALUES (1, '12345@s.whatsapp.net')")
    conn.execute("INSERT INTO chat VALUES (10, 1, 0)")
    conn.execute("INSERT INTO message VALUES (100, 10, NULL, 1700000000000, 'Bob', 0)")
    conn.execute("INSERT INTO message_vcard VALUES (100, 'BEGIN:VCARD\\nFN:Bob\\nEND:VCARD')")

    store = ChatCollection()
    store.set_system("jid_map_exists", False)
    chat = ChatStore("android", "Bob")
    msg = Message(from_me=True, timestamp=1700000000, time="12:00", key_id="k1")
    chat.add_message(100, msg)
    store.add_chat("12345@s.whatsapp.net", chat)

    media_dir = tmp_path / "Media"
    media_dir.mkdir()
    vcard(conn, store, str(media_dir), None, ([], []), True)

    assert msg.mime == "text/x-vcard"
    assert (media_dir / "vCards" / "Bob.vcf").is_file()
