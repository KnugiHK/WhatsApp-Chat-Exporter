import pytest

from Whatsapp_Chat_Exporter import exported_handler
from Whatsapp_Chat_Exporter.data_model import ChatCollection


def test_unrecognized_format_raises_instead_of_hanging(tmp_path):
    chat_file = tmp_path / "chat.txt"
    chat_file.write_text("[12/03/2024, 09:15:22] Alice: hi\n", encoding="utf8")

    with pytest.raises(ValueError, match="Line 1"):
        exported_handler.messages(str(chat_file), ChatCollection())
