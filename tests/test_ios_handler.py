import pytest

from Whatsapp_Chat_Exporter.data_model import Message
from Whatsapp_Chat_Exporter.ios_handler import process_message_data


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
