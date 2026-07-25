import sqlite3
import pytest
from Whatsapp_Chat_Exporter import ios_handler
from Whatsapp_Chat_Exporter.data_model import ChatCollection
from Whatsapp_Chat_Exporter.data_model import Message
from Whatsapp_Chat_Exporter.ios_handler import process_message_data


def make_contacts_db(rows, with_lid=True):
    """Build an in-memory ZWAADDRESSBOOKCONTACT table.

    Each row is (ZWHATSAPPID, ZFULLNAME, ZABOUTTEXT) or, when with_lid is set,
    (ZWHATSAPPID, ZLID, ZFULLNAME, ZABOUTTEXT).
    """
    columns = "ZWHATSAPPID TEXT, ZLID TEXT, ZFULLNAME TEXT, ZABOUTTEXT TEXT"
    if not with_lid:
        columns = "ZWHATSAPPID TEXT, ZFULLNAME TEXT, ZABOUTTEXT TEXT"
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute(f"CREATE TABLE ZWAADDRESSBOOKCONTACT ({columns})")
    placeholders = ", ".join("?" * len(rows[0])) if rows else ""
    for row in rows:
        db.execute(f"INSERT INTO ZWAADDRESSBOOKCONTACT VALUES ({placeholders})", row)
    return db


class TestContactsDuplicateWhatsAppIds:
    """The iOS address book can map several entries to one WhatsApp ID."""

    def test_duplicate_ids_do_not_raise(self):
        """Regression: add_chat() raises ValueError on an existing chat ID."""
        db = make_contacts_db([
            ("1555000@s.whatsapp.net", None, "First Name", None),
            ("1555000@s.whatsapp.net", None, "Second Name", None),
        ])
        data = ChatCollection()
        ios_handler.contacts(db, data)
        assert len(data) == 1

    def test_first_non_empty_values_are_kept(self):
        db = make_contacts_db([
            ("1555000@s.whatsapp.net", None, "First Name", None),
            ("1555000@s.whatsapp.net", None, "Second Name", "hello there"),
        ])
        data = ChatCollection()
        ios_handler.contacts(db, data)
        chat = data.get_chat("1555000@s.whatsapp.net")
        assert chat.name == "First Name"
        # A field left empty by the first row is filled in by a later one.
        assert chat.status == "hello there"

    def test_lid_from_a_later_duplicate_is_registered_as_an_alias(self):
        db = make_contacts_db([
            ("1555000@s.whatsapp.net", None, "First Name", None),
            ("1555000@s.whatsapp.net", "9988@lid", "Second Name", None),
        ])
        data = ChatCollection()
        ios_handler.contacts(db, data)
        chat = data.get_chat("1555000@s.whatsapp.net")
        assert "9988@lid" in chat.aliases
        # The alias must resolve to the same chat.
        assert data.get_chat("9988@lid") is chat

    def test_repeated_lid_is_not_added_twice(self):
        db = make_contacts_db([
            ("1555000@s.whatsapp.net", "9988@lid", "First Name", None),
            ("1555000@s.whatsapp.net", "9988@lid", "Second Name", None),
        ])
        data = ChatCollection()
        ios_handler.contacts(db, data)
        assert data.get_chat("1555000@s.whatsapp.net").aliases == ["9988@lid"]

    def test_distinct_ids_are_still_separate_chats(self):
        db = make_contacts_db([
            ("1555000@s.whatsapp.net", None, "First Name", None),
            ("1555001@s.whatsapp.net", None, "Other Name", None),
        ])
        data = ChatCollection()
        ios_handler.contacts(db, data)
        assert len(data) == 2
        assert data.get_chat("1555001@s.whatsapp.net").name == "Other Name"

    def test_bare_numbers_are_normalised_before_deduplication(self):
        """A bare number and its @s.whatsapp.net form are the same contact."""
        db = make_contacts_db([
            ("1555000", None, "First Name", None),
            ("1555000@s.whatsapp.net", None, "Second Name", None),
        ])
        data = ChatCollection()
        ios_handler.contacts(db, data)
        assert len(data) == 1

    def test_null_ids_are_skipped(self):
        db = make_contacts_db([
            (None, None, "No Id", None),
            ("1555000@s.whatsapp.net", None, "First Name", None),
        ])
        data = ChatCollection()
        ios_handler.contacts(db, data)
        assert len(data) == 1

    def test_works_without_a_zlid_column(self):
        """Older WhatsApp versions have no ZLID column."""
        db = make_contacts_db([
            ("1555000@s.whatsapp.net", "First Name", None),
            ("1555000@s.whatsapp.net", "Second Name", None),
        ], with_lid=False)
        data = ChatCollection()
        ios_handler.contacts(db, data)
        assert len(data) == 1
        assert data.get_chat("1555000@s.whatsapp.net").name == "First Name"


def make_content(metadata):
    return {
        "ZISFROMME": 1,
        "ZMESSAGETYPE": 0,
        "ZMETADATA": metadata,
        "ZTEXT": "hi",
        "ZMESSAGETEXT": None,
    }


def make_message():
    return Message(from_me=1, timestamp=0, time=0, key_id="k", message_type=0)


def quoted_metadata(parent_id):
    """Build a ZMETADATA blob: 0x2A tag, length byte, then the quoted ID."""
    return b"\x2a" + bytes([len(parent_id)]) + parent_id.encode()


@pytest.mark.parametrize("parent_id", ["A" * 20, "B" * 22, "C" * 16])
def test_quoted_reply_detected_for_any_parent_id_length(parent_id):
    message = make_message()
    message_map = {parent_id[:17]: "parent text"}

    process_message_data(
        message, make_content(quoted_metadata(parent_id)), False, None, message_map, False
    )

    assert message.reply == parent_id[:17]
    assert message.quoted_data == "parent text"


def test_non_reply_metadata_starting_with_tag_byte_is_ignored():
    message = make_message()

    # Length byte claims 30 bytes but only 2 follow, so this is not a quoted reply.
    process_message_data(
        message, make_content(b"\x2a\x1e\xff\xfe"), False, None, {}, False
    )

    assert message.reply is None
    assert message.quoted_data is None


def test_no_reply_flag_skips_quoted_reply_parsing():
    message = make_message()
    parent_id = "D" * 20

    process_message_data(
        message,
        make_content(quoted_metadata(parent_id)),
        False,
        None,
        {parent_id[:17]: "parent text"},
        True,
    )

    assert message.reply is None
