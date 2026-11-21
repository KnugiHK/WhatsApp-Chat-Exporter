from Whatsapp_Chat_Exporter import android_handler


class _Message:
    data = None
    mime = None
    meta = False


class _Chat:
    def __init__(self, message_ids):
        self.messages = {i: _Message() for i in message_ids}

    def get_message(self, message_id):
        return self.messages.get(message_id)


class _Data:
    def __init__(self, chats):
        self.chats = chats

    def get_chat(self, jid):
        return self.chats.get(jid)


def _row(message_row_id, vcard, name="Alice"):
    return {
        "message_row_id": message_row_id,
        "key_remote_jid": "123@s.whatsapp.net",
        "vcard": vcard,
        "media_name": name,
    }


def _cards(path):
    return {f.name: f.read_text(encoding="utf-8") for f in path.glob("*.vcf")}


def test_different_vcards_with_the_same_name_keep_their_own_file(tmp_path):
    data = _Data({"123@s.whatsapp.net": _Chat([1, 2])})

    android_handler._process_vcard_row(_row(1, "BEGIN:VCARD first"), str(tmp_path), data)
    android_handler._process_vcard_row(_row(2, "BEGIN:VCARD second"), str(tmp_path), data)

    cards = _cards(tmp_path)
    assert sorted(cards.values()) == ["BEGIN:VCARD first", "BEGIN:VCARD second"]
    second = data.get_chat("123@s.whatsapp.net").get_message(2).data
    second_file = next(name for name, card in cards.items() if card == "BEGIN:VCARD second")
    assert second_file in str(second)


def test_identical_vcard_reuses_its_file(tmp_path):
    data = _Data({"123@s.whatsapp.net": _Chat([1, 2])})

    android_handler._process_vcard_row(_row(1, "BEGIN:VCARD same"), str(tmp_path), data)
    android_handler._process_vcard_row(_row(2, "BEGIN:VCARD same"), str(tmp_path), data)

    assert _cards(tmp_path) == {"Alice.vcf": "BEGIN:VCARD same"}


def test_identical_crlf_vcard_reuses_its_file(tmp_path):
    # vCards use CRLF line endings; text-mode reading would turn them into LF
    data = _Data({"123@s.whatsapp.net": _Chat([1, 2])})
    card = "BEGIN:VCARD\r\nFN:Alice\r\nEND:VCARD\r\n"

    android_handler._process_vcard_row(_row(1, card), str(tmp_path), data)
    android_handler._process_vcard_row(_row(2, card), str(tmp_path), data)

    assert [f.name for f in tmp_path.glob("*.vcf")] == ["Alice.vcf"]
    assert (tmp_path / "Alice.vcf").read_bytes() == card.encode("utf-8")


def test_message_with_several_vcards_links_all_of_them(tmp_path):
    data = _Data({"123@s.whatsapp.net": _Chat([1])})

    android_handler._process_vcard_row(_row(1, "BEGIN:VCARD a", "Alice"), str(tmp_path), data)
    android_handler._process_vcard_row(_row(1, "BEGIN:VCARD b", "Bob"), str(tmp_path), data)

    message = str(data.get_chat("123@s.whatsapp.net").get_message(1).data)
    assert "Alice.vcf" in message and "Bob.vcf" in message
