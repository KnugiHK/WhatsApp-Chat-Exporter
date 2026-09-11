import sqlite3

import pytest

from Whatsapp_Chat_Exporter.android_handler import _get_lid_map, _resolve_mentions
from Whatsapp_Chat_Exporter.data_model import ChatCollection, ChatStore
from Whatsapp_Chat_Exporter.utility import Device

NAMED_PN_JID = "15550001111@s.whatsapp.net"
UNNAMED_PN_JID = "15550002222@s.whatsapp.net"


@pytest.fixture
def data():
    data = ChatCollection()
    data.set_system("lid_map", {"11111111111111": NAMED_PN_JID, "22222222222222": UNNAMED_PN_JID})
    data.add_chat(NAMED_PN_JID, ChatStore(Device.ANDROID, "Alice"))
    return data


def test_mention_resolved_to_contact_name(data):
    assert _resolve_mentions("Hi @11111111111111, see above", data) == "Hi @Alice, see above"


def test_mention_resolved_to_phone_number_without_contact_name(data):
    assert _resolve_mentions("@22222222222222 thanks", data) == "@15550002222 thanks"


def test_unknown_numbers_are_left_untouched(data):
    text = "Call @33333333333333 or 11111111111111 before 10:00"
    assert _resolve_mentions(text, data) == text


def test_no_lid_map_or_no_text():
    data = ChatCollection()
    assert _resolve_mentions("Hi @11111111111111", data) == "Hi @11111111111111"
    assert _resolve_mentions(None, data) is None


def test_get_lid_map():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE jid (_id INTEGER PRIMARY KEY, user TEXT, server TEXT, raw_string TEXT);
        CREATE TABLE jid_map (lid_row_id INTEGER, jid_row_id INTEGER);
        INSERT INTO jid VALUES (1, '11111111111111', 'lid', '11111111111111@lid');
        INSERT INTO jid VALUES (2, '15550001111', 's.whatsapp.net', '15550001111@s.whatsapp.net');
        INSERT INTO jid_map VALUES (1, 2);
    """)
    assert _get_lid_map(db) == {"11111111111111": NAMED_PN_JID}
    db.close()
