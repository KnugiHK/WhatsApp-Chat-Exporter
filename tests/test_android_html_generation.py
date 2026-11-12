from pathlib import Path

import pytest

from Whatsapp_Chat_Exporter import android_handler
from Whatsapp_Chat_Exporter.utility import ROW_SIZE


class _Chat:
    def __init__(self, name):
        self.name = name

    def __len__(self):
        return 1

    def values(self):
        return [self.name]


class _Chats:
    def __init__(self, chats):
        self.chats = chats

    def __len__(self):
        return len(self.chats)

    def __iter__(self):
        return iter(self.chats)

    def get_chat(self, contact):
        return self.chats[contact]


class _PagedChat(_Chat):
    def __init__(self, name):
        super().__init__(name)
        self.messages = [
            SimpleMessage(1, "xx"),
            SimpleMessage(2, ""),
        ]

    def values(self):
        return self.messages

    def get_last_message(self):
        return self.messages[-1]


class SimpleMessage:
    def __init__(self, key_id, data):
        self.key_id = key_id
        self.data = data
        self.meta = False
        self.media = False


@pytest.mark.parametrize(
    "chat_names",
    [
        ("🌍 Clash Of Hemispheres 🌎", "🌎 Clash Of Hemispheres 🌍"),
        ("Same Chat", "same chat"),
    ],
)
def test_create_html_uses_unique_files_for_colliding_names(
    tmp_path, monkeypatch, chat_names
):
    output = tmp_path / "out"
    output.mkdir()
    contacts = ("123-1@g.us", "456-2@g.us")
    chats = _Chats(
        {
            contacts[0]: _Chat(chat_names[0]),
            contacts[1]: _Chat(chat_names[1]),
        }
    )
    monkeypatch.setattr(android_handler, "setup_template", lambda *args: None)
    monkeypatch.setattr(android_handler, "get_status_location", lambda *args: "")

    def render(output_file_name, template, name, messages, *args, **kwargs):
        Path(output_file_name).write_text(name, encoding="utf-8")

    monkeypatch.setattr(android_handler, "rendering", render)

    android_handler.create_html(chats, str(output))

    html_files = list(output.glob("*.html"))
    assert len(html_files) == 2
    assert {path.read_text(encoding="utf-8") for path in html_files} == set(chat_names)


def test_paginated_collision_names_keep_page_numbers_and_links_consistent(
    tmp_path, monkeypatch
):
    output = tmp_path / "out"
    output.mkdir()
    contacts = ("123-1@g.us", "456-2@g.us")
    chats = _Chats(
        {
            contact: _PagedChat("Same Chat")
            for contact in contacts
        }
    )
    rendered = {}
    monkeypatch.setattr(android_handler, "setup_template", lambda *args: None)
    monkeypatch.setattr(android_handler, "get_status_location", lambda *args: "")

    def render(output_file_name, *args, **kwargs):
        rendered[Path(output_file_name).name] = kwargs
        Path(output_file_name).touch()

    monkeypatch.setattr(android_handler, "rendering", render)

    android_handler.create_html(
        chats, str(output), maximum_size=ROW_SIZE + 1
    )

    for base_name in ("Same-Chat", "Same-Chat_1"):
        first_page = f"{base_name}-1.html"
        second_page = f"{base_name}-2.html"
        assert rendered[first_page]["next"] == second_page
        assert rendered[second_page]["previous"] == first_page
    assert set(rendered) == {
        "Same-Chat-1.html",
        "Same-Chat-2.html",
        "Same-Chat_1-1.html",
        "Same-Chat_1-2.html",
    }


def test_create_html_preserves_filename_when_there_is_no_collision(tmp_path, monkeypatch):
    output = tmp_path / "out"
    output.mkdir()
    contact = "123-1@g.us"
    chats = _Chats({contact: _Chat("Distinct Chat")})
    monkeypatch.setattr(android_handler, "setup_template", lambda *args: None)
    monkeypatch.setattr(android_handler, "get_status_location", lambda *args: "")

    def render(output_file_name, *args, **kwargs):
        Path(output_file_name).touch()

    monkeypatch.setattr(android_handler, "rendering", render)

    android_handler.create_html(chats, str(output))

    assert (output / "Distinct-Chat.html").exists()
