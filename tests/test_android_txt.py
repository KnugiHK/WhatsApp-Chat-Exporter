from Whatsapp_Chat_Exporter.android_handler import create_txt
from Whatsapp_Chat_Exporter.data_model import ChatCollection, ChatStore, Message, Timing
from Whatsapp_Chat_Exporter.utility import Device


def make_chat(name, text):
    chat = ChatStore(Device.ANDROID, name=name)
    message = Message(
        from_me=True,
        timestamp=1672531200,
        time="00:00",
        key_id="A",
        timezone_offset=Timing(0),
    )
    message.data = text
    chat.add_message("1", message)
    return chat


def read_txt_files(path):
    return {file.name: file.read_text(encoding="utf8") for file in path.iterdir()}


class TestCreateTxt:
    def test_unique_names_are_unchanged(self, tmp_path):
        """Verify that chats with unique names keep their original file names."""
        data = ChatCollection()
        data.add_chat("111@s.whatsapp.net", make_chat("Alice", "first"))
        data.add_chat("222@s.whatsapp.net", make_chat("Bob", "second"))
        data.add_chat("333@s.whatsapp.net", make_chat(None, "third"))

        create_txt(data, str(tmp_path))

        assert sorted(read_txt_files(tmp_path)) == ["333@s.whatsapp.net.txt", "Alice.txt", "Bob.txt"]

    def test_duplicate_names_do_not_overwrite(self, tmp_path):
        """Verify that chats with the same name are written to separate files."""
        data = ChatCollection()
        data.add_chat("111@s.whatsapp.net", make_chat("Alice", "first"))
        data.add_chat("222@s.whatsapp.net", make_chat("Alice", "second"))
        data.add_chat("123-456@g.us", make_chat("alice", "third"))

        create_txt(data, str(tmp_path))

        files = read_txt_files(tmp_path)
        assert sorted(files) == [
            "Alice (222@s.whatsapp.net).txt",
            "Alice.txt",
            "alice (123-456@g.us).txt",
        ]
        assert "first" in files["Alice.txt"]
        assert "second" in files["Alice (222@s.whatsapp.net).txt"]
        assert "third" in files["alice (123-456@g.us).txt"]

    def test_duplicate_names_keep_line_format(self, tmp_path):
        """Verify that the suffix only affects the file name."""
        data = ChatCollection()
        data.add_chat("111@s.whatsapp.net", make_chat("Alice", "first"))
        data.add_chat("222@s.whatsapp.net", make_chat("Alice", "second"))

        create_txt(data, str(tmp_path))

        files = read_txt_files(tmp_path)
        assert files["Alice (222@s.whatsapp.net).txt"].endswith("00:00] You: second\n")

    def test_suffixed_name_already_in_use(self, tmp_path):
        """Verify that a chat named like a suffixed file name does not cause an overwrite."""
        data = ChatCollection()
        data.add_chat("111@s.whatsapp.net", make_chat("Alice (222@s.whatsapp.net)", "first"))
        data.add_chat("333@s.whatsapp.net", make_chat("Alice", "second"))
        data.add_chat("222@s.whatsapp.net", make_chat("Alice", "third"))

        create_txt(data, str(tmp_path))

        files = read_txt_files(tmp_path)
        assert len(files) == 3
        assert "first" in files["Alice (222@s.whatsapp.net).txt"]
        assert "second" in files["Alice.txt"]
        assert "third" in files["Alice (222@s.whatsapp.net) 2.txt"]
