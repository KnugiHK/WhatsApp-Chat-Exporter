from Whatsapp_Chat_Exporter import exported_handler
from Whatsapp_Chat_Exporter.data_model import ChatCollection


def test_continuation_line_with_dash(tmp_path):
    chat_file = tmp_path / "chat.txt"
    chat_file.write_text(
        "12/03/2024, 09:16 - Alice: Which flight should we take?\n"
        "Option A - leaves at 7\n"
        "12/03/2024, 09:17 - Bob: B for sure\n",
        encoding="utf8",
    )

    data = exported_handler.messages(str(chat_file), ChatCollection(), assume_first_as_me=True)

    messages = list(data.get_chat("ExportedChat").values())
    assert len(messages) == 2
    assert "Option A - leaves at 7" in messages[0].data
