import sqlite3

import pytest

from Whatsapp_Chat_Exporter.android_handler import _get_reactions
from Whatsapp_Chat_Exporter.data_model import ChatCollection, ChatStore, Message
from Whatsapp_Chat_Exporter.utility import Device

# Minimal subset of the new msgstore.db schema used by _get_reactions.
SCHEMA = """
CREATE TABLE jid (_id INTEGER PRIMARY KEY, user TEXT, server TEXT, raw_string TEXT);
CREATE TABLE jid_map (lid_row_id INTEGER, jid_row_id INTEGER);
CREATE TABLE chat (_id INTEGER PRIMARY KEY, jid_row_id INTEGER);
CREATE TABLE message_add_on (_id INTEGER PRIMARY KEY, chat_row_id INTEGER, parent_message_row_id INTEGER,
                             from_me INTEGER, sender_jid_row_id INTEGER);
CREATE TABLE message_add_on_reaction (message_add_on_row_id INTEGER, reaction TEXT, sender_timestamp INTEGER);
"""

GROUP_JID = "120363000000000000@g.us"
PRIVATE_PN_JID = "15550002222@s.whatsapp.net"


@pytest.fixture
def db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    db.executemany("INSERT INTO jid VALUES (?, ?, ?, ?)", [
        (1, "120363000000000000", "g.us", GROUP_JID),
        (2, "11111111111111", "lid", "11111111111111@lid"),  # group member, known by LID
        (3, "15550001111", "s.whatsapp.net", "15550001111@s.whatsapp.net"),  # that member's phone number
        (4, "22222222222222", "lid", "22222222222222@lid"),  # 1:1 chat stored under a LID
        (5, "15550002222", "s.whatsapp.net", PRIVATE_PN_JID),  # that chat's phone number
    ])
    db.executemany("INSERT INTO jid_map VALUES (?, ?)", [(2, 3), (4, 5)])
    db.executemany("INSERT INTO chat VALUES (?, ?)", [(10, 1), (11, 4)])
    db.executemany("INSERT INTO message_add_on VALUES (?, ?, ?, ?, ?)", [
        (100, 10, 1000, 0, 2),  # LID member reacts in the group
        (101, 11, 1001, 0, 4),  # contact reacts in the LID-keyed 1:1 chat
    ])
    db.executemany("INSERT INTO message_add_on_reaction VALUES (?, ?, ?)", [(100, "👍", 0), (101, "❤️", 0)])
    yield db
    db.close()


def _collection(jid_map_exists, private_chat_jid=PRIVATE_PN_JID):
    """Chats keyed the way the message query keys them (phone number JID when jid_map resolves a LID)."""
    data = ChatCollection()
    data.set_system("jid_map_exists", jid_map_exists)
    for chat_jid, message_id in ((GROUP_JID, 1000), (private_chat_jid, 1001)):
        chat = data.add_chat(chat_jid, ChatStore(Device.ANDROID))
        chat.add_message(message_id, Message(from_me=False, timestamp=1700000000, time=1700000000, key_id=message_id))
    return data


def test_reaction_sender_lid_resolved_to_phone_number(db):
    data = _collection(jid_map_exists=True)
    _get_reactions(db, data)
    assert data[GROUP_JID].get_message(1000).reactions == {"15550001111": "👍"}


def test_reaction_in_lid_keyed_chat_is_not_dropped(db):
    data = _collection(jid_map_exists=True)
    _get_reactions(db, data)
    assert data[PRIVATE_PN_JID].get_message(1001).reactions == {"15550002222": "❤️"}


def test_reactions_without_jid_map_table(db):
    db.execute("DROP TABLE jid_map")
    data = _collection(jid_map_exists=False, private_chat_jid="22222222222222@lid")
    _get_reactions(db, data)
    assert data[GROUP_JID].get_message(1000).reactions == {"11111111111111": "👍"}
    assert data["22222222222222@lid"].get_message(1001).reactions == {"22222222222222": "❤️"}
