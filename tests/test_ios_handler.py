import sqlite3

import pytest

from Whatsapp_Chat_Exporter import ios_handler
from Whatsapp_Chat_Exporter.data_model import ChatCollection


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
