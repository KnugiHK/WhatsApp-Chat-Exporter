import base64
import sqlite3
import pytest
import unittest
from Whatsapp_Chat_Exporter.utility import Device, normalize_phone_label
from Whatsapp_Chat_Exporter import ios_handler
from Whatsapp_Chat_Exporter.data_model import ChatCollection, ChatStore
from Whatsapp_Chat_Exporter.data_model import Message, Timing
from Whatsapp_Chat_Exporter.ios_handler import process_message_data


def encoded_info(fields):
    return base64.b64encode(fields).decode()


def test_is_edited_detects_field_seven():
    edited = encoded_info(b"\x08\x01\x3a\x03abc")
    assert ios_handler._is_edited(0, edited) is True


def test_is_edited_without_field_seven():
    assert ios_handler._is_edited(0, encoded_info(b"\x08\x01\x48\x01")) is False


@pytest.mark.parametrize("message_type,info", [
    (0, None),
    (0, ""),
    (0, "not base64!"),
    (1, encoded_info(b"\x3a\x03abc")),
])
def test_is_edited_ignores_other_values(message_type, info):
    assert ios_handler._is_edited(message_type, info) is False


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
    return Message(from_me=1, timestamp=1792700001, time=1792700001, key_id="k", message_type=0)


def quoted_metadata(parent_id):
    """Build a ZMETADATA blob: 0x2A tag, length byte, then the quoted ID."""
    return b"\x2a" + bytes([len(parent_id)]) + parent_id.encode()


@pytest.mark.parametrize("parent_id", ["A" * 20, "B" * 22, "C" * 16])
def test_quoted_reply_detected_for_any_parent_id_length(parent_id):
    message = make_message()
    message_map = {parent_id: "parent text"}

    process_message_data(
        message, make_content(quoted_metadata(parent_id)), False, None, message_map
    )

    assert message.reply == parent_id
    assert message.quoted_data == "parent text"


def test_non_reply_metadata_starting_with_tag_byte_is_ignored():
    message = make_message()

    # Length byte claims 30 bytes but only 2 follow, so this is not a quoted reply.
    process_message_data(
        message, make_content(b"\x2a\x1e\xff\xfe"), False, None, {}
    )

    assert message.reply is None
    assert message.quoted_data is None


class TestNormalizePhoneLabel(unittest.TestCase):
    """Tests for normalize_phone_label."""

    def test_bidi_formatted_number_matches_plain_form(self):
        """Both backups of the same number yield the same bare number."""
        before = "+1 (202) 555-0123"
        after = "\u202a+1\u00a0(202)\u00a0555\u20110123\u202c"

        self.assertEqual(normalize_phone_label(before), "+1202555-0123")
        self.assertEqual(normalize_phone_label(after), "+1202555-0123")
        # The whole point: both backups produce the same sender label
        self.assertEqual(
            normalize_phone_label(before),
            normalize_phone_label(after),
        )

    def test_isolates_thin_spaces_and_non_breaking_hyphens(self):
        label = "\u2066+1\u2009202\u200a555\u20110123\u2069"
        self.assertEqual(normalize_phone_label(label), "+1202555-0123")

    def test_left_to_right_mark_is_removed(self):
        label = "\u200e+1 \u200f(202) 555-0123"
        self.assertEqual(normalize_phone_label(label), "+1202555-0123")

    def test_fullwidth_digits_are_folded(self):
        label = "\uff0b\uff11 (\uff12\uff10\uff12) \uff15\uff15\uff15-\uff10\uff11\uff12\uff13"
        self.assertEqual(normalize_phone_label(label), "+1202555-0123")

    def test_dash_variants_become_the_ascii_hyphen(self):
        for label in (
            "+1 (202) 555\u20110123",  # non-breaking hyphen
            "+1 (202) 555\u20130123",  # en dash
            "+1 (202) 555\u20140123",  # em dash
            "+1 (202) 555\u20150123",  # horizontal bar
        ):
            with self.subTest(label=label):
                self.assertEqual(normalize_phone_label(label), "+1202555-0123")

    def test_decorative_separators_are_removed(self):
        self.assertEqual(normalize_phone_label("+1.202.555.0123"), "+12025550123")
        self.assertEqual(normalize_phone_label("+1/202/555/0123"), "+12025550123")

    def test_plain_digits_unchanged(self):
        self.assertEqual(normalize_phone_label("12025550123"), "12025550123")

    def test_contact_names_are_preserved(self):
        """Labels that are not phone-like must be returned untouched."""
        for name in (
            "John Doe",
            "Mom \U0001f618",
            "\u202aOffice Team\u202c",
            "3 Amigos",
            "+1 (202) 555-0123 ext. 42",
        ):
            with self.subTest(name=name):
                self.assertEqual(normalize_phone_label(name), name)

    def test_empty_and_none(self):
        self.assertEqual(normalize_phone_label(""), "")
        self.assertIsNone(normalize_phone_label(None))

    def test_no_digits_is_not_phone_like(self):
        label = "\u202a+\u00a0-()\u202c"
        self.assertEqual(normalize_phone_label(label), label)

    def test_normalization_is_idempotent(self):
        label = "\u202a+1\u00a0(202)\u00a0555\u20110123\u202c"
        once = normalize_phone_label(label)
        self.assertEqual(once, "+1202555-0123")
        self.assertEqual(normalize_phone_label(once), once)


class TestSenderAssignment(unittest.TestCase):
    """Sender labels are reduced to bare phone numbers when assigned."""

    MEMBER_JID = "12025550123@s.whatsapp.net"
    BIDI_LABEL = "\u202a+1\u00a0(202)\u00a0555\u20110123\u202c"
    BARE_LABEL = "+1202555-0123"

    def _make_data(self, name=None):
        data = ChatCollection()
        data.add_chat(self.MEMBER_JID, ChatStore(Device.IOS, name))
        return data

    def _make_message(self):
        return Message(
            from_me=0,
            timestamp=0,
            time="00:00",
            key_id="key",
            timezone_offset=Timing(0),
            message_type=1
        )

    def _make_content(self):
        return {
            "ZISFROMME": 0,
            "ZMEMBERJID": self.MEMBER_JID,
            "ZMESSAGETYPE": 1,
            "ZMETADATA": None,
            "ZTEXT": "Hello there",
        }

    def _make_system_content(self, message_type, event, **overrides):
        content = self._make_content()
        content.update({
            "ZMESSAGETYPE": message_type,
            "ZGROUPEVENTTYPE": event,
            "ZTEXT": None,
            "ZCONTACTJID": self.MEMBER_JID,
        })
        content.update(overrides)
        return content

    def test_group_system_messages(self):
        data = self._make_data("John Doe")
        expected = {
            (10, 3): "Your security code with John Doe changed",
            (6, 2): "John Doe was added",
            (6, 15): "John Doe joined using a group link",
            (6, 30): "Message history was shared with John Doe",
            (6, 3): "John Doe left",
            (6, 12): "John Doe created this group",
            (60, 2): "John Doe sent you message history",
            (10, 58): "John Doe pinned a message",
            (10, 2): "Messages and calls are end-to-end encrypted",
        }
        for (message_type, event), text in expected.items():
            message = self._make_message()
            ios_handler.process_message_data(message, self._make_system_content(message_type, event), True, data, {})
            self.assertEqual(message.data, text)
            self.assertTrue(message.meta)

    def test_direct_system_messages(self):
        data = self._make_data("John Doe")
        expected = {
            (10, 3): "Your security code with John Doe changed",
            (10, 2): "Messages and calls are end-to-end encrypted",
            (59, 0): "Voice or video call",
            (10, 1): "Missed voice call",
            (12, 0): "Waiting for this message",
            (10, 38): "This business changed how it manages this chat",
        }
        for (message_type, event), text in expected.items():
            message = self._make_message()
            ios_handler.process_message_data(message, self._make_system_content(message_type, event), False, data, {})
            self.assertEqual(message.data, text)
            self.assertTrue(message.meta)

    def test_unknown_system_event_is_left_unchanged(self):
        data = self._make_data("John Doe")
        message = self._make_message()
        ios_handler.process_message_data(message, self._make_system_content(10, 99), True, data, {})
        self.assertIsNone(message.data)

    def test_message_history_sent_by_self(self):
        data = self._make_data("John Doe")
        message = self._make_message()
        content = self._make_system_content(60, 2, ZISFROMME=1)
        ios_handler.process_message_data(message, content, True, data, {})
        self.assertEqual(message.data, "You sent message history")

    def test_system_event_with_text_keeps_its_text(self):
        data = self._make_data("John Doe")
        message = self._make_message()
        content = self._make_system_content(10, 3, ZTEXT="Existing text")
        ios_handler.process_message_data(message, content, True, data, {})
        self.assertEqual(message.data, "Existing text")

    def test_process_message_data_normalizes_sender(self):
        data = self._make_data(self.BIDI_LABEL)
        message = self._make_message()

        ios_handler.process_message_data(message, self._make_content(), True, data, {})

        self.assertEqual(message.sender, self.BARE_LABEL)
        self.assertEqual(message.data, "Hello there")

    def test_process_message_data_sender_fallback_normalized(self):
        data = self._make_data()
        message = self._make_message()

        ios_handler.process_message_data(message, self._make_content(), True, data, {})

        # The fallback JID local part is a bare number already
        self.assertEqual(message.sender, "12025550123")

    def test_process_message_data_preserves_contact_name(self):
        data = self._make_data("John Doe")
        message = self._make_message()

        ios_handler.process_message_data(message, self._make_content(), True, data, {})

        self.assertEqual(message.sender, "John Doe")

    def test_process_call_record_normalizes_sender(self):
        data = self._make_data(self.BIDI_LABEL)
        content = {
            "ZCALLIDSTRING": "call-1",
            "ZGROUPCALLCREATORUSERJIDSTRING": self.MEMBER_JID,
            "ZGROUPJIDSTRING": None,
            "ZDATE": 0,
            "ZOUTCOME": 0,
            "ZDURATION": 30,
            "ZVIDEO": 0,
            "ZMISSED": 1,
            "ZINCOMING": 1,
            "bytes_transferred": 100,
        }
        chat = ChatStore(Device.ANDROID, "WhatsApp Calls")

        ios_handler.process_call_record(content, chat, data, Timing(0))

        call = chat.get_message("call-1")
        self.assertEqual(call.sender, self.BARE_LABEL)


if __name__ == '__main__':
    unittest.main()
