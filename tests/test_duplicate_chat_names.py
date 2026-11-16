from Whatsapp_Chat_Exporter.android_handler import create_html
from Whatsapp_Chat_Exporter.data_model import ChatCollection, ChatStore, Message


def test_create_html_preserves_chats_with_duplicate_names(tmp_path):
    data = ChatCollection()
    chat1 = ChatStore("GROUP", "Family")
    chat1.add_message(1, Message(from_me=True, timestamp=1700000000, time="10:00", key_id="1"))
    chat1.get_message(1).data = "First group message"
    data.add_chat("111@g.us", chat1)

    chat2 = ChatStore("GROUP", "Family")
    chat2.add_message(2, Message(from_me=False, timestamp=1700000100, time="10:01", key_id="2"))
    chat2.get_message(2).data = "Second group message"
    data.add_chat("111@lid", chat2)

    out_dir = tmp_path / "html_out"
    create_html(data, str(out_dir), headline="Chat history for ??")

    html_files = sorted(p.name for p in out_dir.glob("*.html"))
    assert html_files == ["111-Family.html", "111-Family_2.html"]
    assert "First group message" in (out_dir / "111-Family.html").read_text(encoding="utf-8")
    assert "Second group message" in (out_dir / "111-Family_2.html").read_text(encoding="utf-8")
