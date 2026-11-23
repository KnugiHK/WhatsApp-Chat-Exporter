import re
from pathlib import Path

from Whatsapp_Chat_Exporter.data_model import ChatCollection, ChatStore, Message
from Whatsapp_Chat_Exporter.ios_handler import process_vcard_item


def _make_store(jid: str, msg_ids: list[int]) -> tuple[ChatCollection, dict[int, Message]]:
    store = ChatCollection()
    chat = ChatStore("ios", "Test Chat")
    msgs = {}
    for mid in msg_ids:
        msg = Message(from_me=True, timestamp=1700000000 + mid, time="12:00", key_id=f"k{mid}")
        chat.add_message(mid, msg)
        msgs[mid] = msg
    store.add_chat(jid, chat)
    return store, msgs


def _extract_href(markup_val) -> str:
    m = re.search(r'href="([^"]+)"', str(markup_val))
    assert m is not None
    return m.group(1)


def test_different_contacts_with_colliding_sanitized_names_do_not_overwrite(tmp_path: Path):
    vcard_dir = tmp_path / "vCards"
    vcard_dir.mkdir()
    store, msgs = _make_store("123@s.whatsapp.net", [1, 2])

    process_vcard_item(
        {
            "ZVCARDNAME": "Sam",
            "ZVCARDSTRING": "BEGIN:VCARD\nFN:Sam One\nTEL:111\nEND:VCARD",
            "ZCONTACTJID": "123@s.whatsapp.net",
            "ZMESSAGE": 1,
        },
        str(vcard_dir),
        store,
    )
    process_vcard_item(
        {
            "ZVCARDNAME": "Sam 🌻",
            "ZVCARDSTRING": "BEGIN:VCARD\nFN:Sam Two\nTEL:222\nEND:VCARD",
            "ZCONTACTJID": "123@s.whatsapp.net",
            "ZMESSAGE": 2,
        },
        str(vcard_dir),
        store,
    )

    href1 = _extract_href(msgs[1].data)
    href2 = _extract_href(msgs[2].data)
    assert href1 != href2
    assert Path(href1).read_text(encoding="utf-8") != Path(href2).read_text(encoding="utf-8")
    assert "TEL:111" in Path(href1).read_text(encoding="utf-8")
    assert "TEL:222" in Path(href2).read_text(encoding="utf-8")


def test_identical_vcard_with_case_variant_name_reuses_exact_disk_filename(tmp_path: Path):
    vcard_dir = tmp_path / "vCards"
    vcard_dir.mkdir()
    store, msgs = _make_store("123@s.whatsapp.net", [1, 2])
    card = "BEGIN:VCARD\nFN:Jo Bloggs\nTEL:999\nEND:VCARD"

    process_vcard_item(
        {
            "ZVCARDNAME": "JO BLOGGS",
            "ZVCARDSTRING": card,
            "ZCONTACTJID": "123@s.whatsapp.net",
            "ZMESSAGE": 1,
        },
        str(vcard_dir),
        store,
    )
    process_vcard_item(
        {
            "ZVCARDNAME": "Jo Bloggs",
            "ZVCARDSTRING": card,
            "ZCONTACTJID": "123@s.whatsapp.net",
            "ZMESSAGE": 2,
        },
        str(vcard_dir),
        store,
    )

    href1 = Path(_extract_href(msgs[1].data)).name
    href2 = Path(_extract_href(msgs[2].data)).name
    disk_files = [p.name for p in vcard_dir.iterdir()]
    assert href1 in disk_files
    assert href2 in disk_files
