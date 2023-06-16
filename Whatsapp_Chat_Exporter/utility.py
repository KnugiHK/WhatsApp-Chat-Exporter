import json
from bleach import clean as sanitize
from markupsafe import Markup
from datetime import datetime
from enum import IntEnum, StrEnum


MAX_SIZE = 4 * 1024 * 1024  # Default 4MB
ROW_SIZE = 0x300


def sanitize_except(html):
    return Markup(sanitize(html, tags=["br"]))


def determine_day(last, current):
    last = datetime.fromtimestamp(last).date()
    current = datetime.fromtimestamp(current).date()
    if last == current:
        return None
    else:
        return current


def check_update():
    import urllib.request
    import json
    from sys import platform
    from .__init__ import __version__

    package_url_json = "https://pypi.org/pypi/whatsapp-chat-exporter/json"
    try:
        raw = urllib.request.urlopen(package_url_json)
    except Exception:
        print("Failed to check for updates.")
        return 1
    else:
        with raw:
            package_info = json.load(raw)
            latest_version = tuple(map(int, package_info["info"]["version"].split(".")))
            current_version = tuple(map(int, __version__.split(".")))
            if current_version < latest_version:
                print("===============Update===============")
                print("A newer version of WhatsApp Chat Exporter is available.")
                print("Current version: " + __version__)
                print("Latest version: " + package_info["info"]["version"])
                if platform == "win32":
                    print("Update with: pip install --upgrade whatsapp-chat-exporter")
                else:
                    print("Update with: pip3 install --upgrade whatsapp-chat-exporter")
                print("====================================")
            else:
                print("You are using the latest version of WhatsApp Chat Exporter.")
    return 0


def rendering(
        output_file_name,
        template,
        name,
        msgs,
        contact,
        w3css,
        next,
        my_avatar,
        their_avatar,
        their_avatar_thumb
    ):
    if their_avatar_thumb is None and their_avatar is not None:
        their_avatar_thumb = their_avatar
    with open(output_file_name, "w", encoding="utf-8") as f:
        f.write(
            template.render(
                name=name,
                msgs=msgs,
                my_avatar=my_avatar,
                their_avatar=their_avatar,
                their_avatar_thumb=their_avatar_thumb,
                w3css=w3css,
                next=next
            )
        )


class Device(StrEnum):
    IOS = "ios"
    ANDROID = "android"
    EXPORTED = "exported"


def import_from_json(json_file, data):
    from Whatsapp_Chat_Exporter.data_model import ChatStore, Message
    with open(json_file, "r") as f:
        temp_data = json.loads(f.read())
    total_row_number = len(tuple(temp_data.keys()))
    print(f"Importing chats from JSON...(0/{total_row_number})", end="\r")
    for index, (jid, chat_data) in enumerate(temp_data.items()):
        chat = ChatStore(chat_data["type"], chat_data["name"])
        chat.my_avatar = chat_data["my_avatar"]
        chat.their_avatar = chat_data["their_avatar"]
        chat.their_avatar_thumb = chat_data["their_avatar_thumb"]
        for id, msg in chat_data["messages"].items():
            message = Message(
                msg["from_me"],
                msg["timestamp"],
                msg["time"],
                msg["key_id"],
            )
            message.media = msg["media"]
            message.meta = msg["meta"]
            message.data = msg["data"]
            message.sender = msg["sender"]
            message.safe = msg["safe"]
            message.reply = msg["reply"]
            message.quoted_data = msg["quoted_data"]
            message.caption = msg["caption"]
            message.thumb = msg["thumb"]
            message.sticker = msg["sticker"]
            chat.add_message(id, message)
        data[jid] = chat
        print(f"Importing chats from JSON...({index + 1}/{total_row_number})", end="\r")


# Android Specific
CRYPT14_OFFSETS = (
    {"iv": 67, "db": 191},
    {"iv": 67, "db": 190},
    {"iv": 66, "db": 99},
    {"iv": 67, "db": 193},
    {"iv": 67, "db": 194},
)


class Crypt(IntEnum):
    CRYPT15 = 15
    CRYPT14 = 14
    CRYPT12 = 12


def brute_force_offset(max_iv=200, max_db=200):
    for iv in range(0, max_iv):
        for db in range(0, max_db):
            yield iv, iv + 16, db


# iOS Specific
APPLE_TIME = datetime.timestamp(datetime(2001, 1, 1))
