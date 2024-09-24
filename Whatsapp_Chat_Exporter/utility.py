import jinja2
import json
import os
import unicodedata
import re
import math
from bleach import clean as sanitize
from markupsafe import Markup
from datetime import datetime, timedelta
from enum import IntEnum
from Whatsapp_Chat_Exporter.data_model import ChatStore
try:
    from enum import StrEnum, IntEnum
except ImportError:
    # < Python 3.11
    from enum import Enum
    class StrEnum(str, Enum):
        pass

    class IntEnum(int, Enum):
        pass

MAX_SIZE = 4 * 1024 * 1024  # Default 4MB
ROW_SIZE = 0x3D0


def convert_time_unit(time_second: int):
    time = str(timedelta(seconds=time_second))
    if "day" not in time:
        if time_second < 1:
            time = "less than a second"
        elif time_second == 1:
            time = "a second"
        elif time_second < 60:
            time = time[5:][1 if time_second < 10 else 0:] + " seconds"
        elif time_second == 60:
            time = "a minute"
        elif time_second < 3600:
            time = time[2:] + " minutes"
        elif time_second == 3600:
            time = "an hour"
        else:
            time += " hour"
    return time


def bytes_to_readable(size_bytes: int):
    """From https://stackoverflow.com/a/14822210/9478891 
    Authors: james-sapam & other contributors
    Licensed under CC BY-SA 3.0
    See git commit logs for changes, if any.
    """
    if size_bytes == 0:
       return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return "%s %s" % (s, size_name[i])


def readable_to_bytes(size_str: str):
    SIZE_UNITS = {
        'B': 1,
        'KB': 1024,
        'MB': 1024**2,
        'GB': 1024**3,
        'TB': 1024**4,
        'PB': 1024**5,
        'EB': 1024**6,
        'ZB': 1024**7, 
        'YB': 1024**8
    }
    size_str = size_str.upper().strip()
    number, unit = size_str[:-2].strip(), size_str[-2:].strip()
    if unit not in SIZE_UNITS or not number.isnumeric():
        raise ValueError("Invalid input for size_str. Example: 1024GB")
    return int(number) * SIZE_UNITS[unit]


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
        chat,
    ):
    if chat.their_avatar_thumb is None and chat.their_avatar is not None:
        their_avatar_thumb = chat.their_avatar
    else:
        their_avatar_thumb = chat.their_avatar_thumb
    with open(output_file_name, "w", encoding="utf-8") as f:
        f.write(
            template.render(
                name=name,
                msgs=msgs,
                my_avatar=chat.my_avatar,
                their_avatar=chat.their_avatar,
                their_avatar_thumb=their_avatar_thumb,
                w3css=w3css,
                next=next,
                status=chat.status,
                media_base=chat.media_base
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
        chat = ChatStore(chat_data.get("type"), chat_data.get("name"))
        chat.my_avatar = chat_data.get("my_avatar")
        chat.their_avatar = chat_data.get("their_avatar")
        chat.their_avatar_thumb = chat_data.get("their_avatar_thumb")
        chat.status = chat_data.get("status")
        for id, msg in chat_data.get("messages").items():
            message = Message(
                msg["from_me"],
                msg["timestamp"],
                msg["time"],
                msg["key_id"],
            )
            message.media = msg.get("media")
            message.meta = msg.get("meta")
            message.data = msg.get("data")
            message.sender = msg.get("sender")
            message.safe = msg.get("safe")
            message.mime = msg.get("mime")
            message.reply = msg.get("reply")
            message.quoted_data = msg.get("quoted_data")
            message.caption = msg.get("caption")
            message.thumb = msg.get("thumb")
            message.sticker = msg.get("sticker")
            chat.add_message(id, message)
        data[jid] = chat
        print(f"Importing chats from JSON...({index + 1}/{total_row_number})", end="\r")


def sanitize_filename(file_name: str):
    return "".join(x for x in file_name if x.isalnum() or x in "- ")


def get_file_name(contact: str, chat: ChatStore):
    if "@" not in contact and contact not in ("000000000000000", "000000000000001", "ExportedChat"):
        raise ValueError("Unexpected contact format: " + contact)
    phone_number = contact.split('@')[0]
    if "-" in contact and chat.name is not None:
        file_name = ""
    else:
        file_name = phone_number

    if chat.name is not None:
        if file_name != "":
            file_name += "-"
        file_name += chat.name.replace("/", "-").replace("\\", "-")
        name = chat.name
    else:
        name = phone_number

    return sanitize_filename(file_name), name


def get_chat_condition(filter, include, columns, jid=None, platform=None):
    if filter is not None:
        conditions = []
        if len(columns) < 2 and jid is not None:
            raise ValueError("There must be at least two elements in argument columns if jid is not None")
        if jid is not None:
            if platform == "android":
                is_group = f"{jid}.type == 1"
            elif platform == "ios":
                is_group = f"{jid} IS NOT NULL"
            else:
                raise ValueError("Only android and ios are supported for argument platform if jid is not None")
        for index, chat in enumerate(filter):
            if include:
                conditions.append(f"{' OR' if index > 0 else ''} {columns[0]} LIKE '%{chat}%'")
                if len(columns) > 1:
                    conditions.append(f" OR ({columns[1]} LIKE '%{chat}%' AND {is_group})")
            else:
                conditions.append(f"{' AND' if index > 0 else ''} {columns[0]} NOT LIKE '%{chat}%'")
                if len(columns) > 1:
                    conditions.append(f" AND ({columns[1]} NOT LIKE '%{chat}%' AND {is_group})")
        return f"AND ({' '.join(conditions)})"
    else:
        return ""

def _is_message_empty(message):
    return (message.data is None or message.data == "") and not message.media

def chat_is_empty(chat: ChatStore):
    return len(chat.messages) == 0 or all(_is_message_empty(message) for message in chat.messages.values())


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


class DbType(StrEnum):
    MESSAGE = "message"
    CONTACT = "contact"


def brute_force_offset(max_iv=200, max_db=200):
    for iv in range(0, max_iv):
        for db in range(0, max_db):
            yield iv, iv + 16, db


def determine_metadata(content, init_msg):
    msg = init_msg if init_msg else ""
    if content["is_me_joined"] == 1:  # Override
        return f"You were added into the group by {msg}"
    if content["action_type"] == 1:
        msg += f''' changed the group name to "{content['data']}"'''
    elif content["action_type"] == 4:
        msg += " was added to the group"
    elif content["action_type"] == 5:
        msg += " left the group"
    elif content["action_type"] == 6:
        msg += f" changed the group icon"
    elif content["action_type"] == 7:
        msg = "You were removed"
    elif content["action_type"] == 8:
        msg += ("WhatsApp Internal Error Occurred: "
                "you cannot send message to this group")
    elif content["action_type"] == 9:
        msg += " created a broadcast channel"
    elif content["action_type"] == 10:
        try:
            old = content['old_jid'].split('@')[0]
            new = content['new_jid'].split('@')[0]
        except (AttributeError, IndexError):
            return None
        else:
            msg = f"{old} changed their number to {new}"
    elif content["action_type"] == 11:
        msg += f''' created a group with name: "{content['data']}"'''
    elif content["action_type"] == 12:
        msg += f" added someone"  # TODO: Find out who
    elif content["action_type"] == 13:
        return  # Someone left the group
    elif content["action_type"] == 14:
        msg += f" removed someone"  # TODO: Find out who
    elif content["action_type"] == 15:
        return  # Someone promoted someone as an admin
    elif content["action_type"] == 18:
        if msg != "You":
            msg = f"The security code between you and {msg} changed"
        else:
            msg = "The security code in this chat changed"
    elif content["action_type"] == 19:
        msg = "This chat is now end-to-end encrypted"
    elif content["action_type"] == 20:
        msg = "Someone joined this group by using a invite link"  # TODO: Find out who
    elif content["action_type"] == 27:
        msg += " changed the group description to:<br>"
        msg += content['data'].replace("\n", '<br>')
    elif content["action_type"] == 28:
        try:
            old = content['old_jid'].split('@')[0]
            new = content['new_jid'].split('@')[0]
        except (AttributeError, IndexError):
            return None
        else:
            msg = f"{old} changed their number to {new}"
    elif content["action_type"] == 46:
        return # Voice message in PM??? Seems no need to handle.
    elif content["action_type"] == 47:
        msg = "The contact is an official business account"
    elif content["action_type"] == 50:
        msg = "The contact's account type changed from business to standard"
    elif content["action_type"] == 56:
        msg = "Messgae timer was enabled/updated/disabled"
    elif content["action_type"] == 57:
        if msg != "You":
            msg = f"The security code between you and {msg} changed"
        else:
            msg = "The security code in this chat changed"
    elif content["action_type"] == 58:
        msg = "You blocked this contact"
    elif content["action_type"] == 67:
        return  # (PM) this contact use secure service from Facebook???
    elif content["action_type"] == 69:
        return  # (PM) this contact use secure service from Facebook??? What's the difference with 67????
    else:
        return  # Unsupported
    return msg


def get_status_location(output_folder, offline_static):
    w3css = "https://www.w3schools.com/w3css/4/w3.css"
    if not offline_static:
        return w3css
    import urllib.request
    static_folder = os.path.join(output_folder, offline_static)
    if not os.path.isdir(static_folder):
        os.mkdir(static_folder)
    w3css_path = os.path.join(static_folder, "w3.css")
    if not os.path.isfile(w3css_path):
        with urllib.request.urlopen(w3css) as resp:
            with open(w3css_path, "wb") as f: f.write(resp.read())
    w3css = os.path.join(offline_static, "w3.css")


def setup_template(template, no_avatar):
    if template is None:
        template_dir = os.path.dirname(__file__)
        template_file = "whatsapp.html"
    else:
        template_dir = os.path.dirname(template)
        template_file = os.path.basename(template)
    template_loader = jinja2.FileSystemLoader(searchpath=template_dir)
    template_env = jinja2.Environment(loader=template_loader, autoescape=True)
    template_env.globals.update(
        determine_day=determine_day,
        no_avatar=no_avatar
    )
    template_env.filters['sanitize_except'] = sanitize_except
    return template_env.get_template(template_file)

# iOS Specific
APPLE_TIME = datetime.timestamp(datetime(2001, 1, 1))


def slugify(value, allow_unicode=False):
    """
    Taken from https://github.com/django/django/blob/master/django/utils/text.py
    Convert to ASCII if 'allow_unicode' is False. Convert spaces or repeated
    dashes to single dashes. Remove characters that aren't alphanumerics,
    underscores, or hyphens. Convert to lowercase. Also strip leading and
    trailing whitespace, dashes, and underscores.
    """
    value = str(value)
    if allow_unicode:
        value = unicodedata.normalize('NFKC', value)
    else:
        value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^\w\s-]', '', value.lower())
    return re.sub(r'[-\s]+', '-', value).strip('-_')


class WhatsAppIdentifier(StrEnum):
    MESSAGE = "7c7fba66680ef796b916b067077cc246adacf01d"
    CONTACT = "b8548dc30aa1030df0ce18ef08b882cf7ab5212f"
    DOMAIN = "AppDomainGroup-group.net.whatsapp.WhatsApp.shared"


class WhatsAppBusinessIdentifier(StrEnum):
    MESSAGE = "724bd3b98b18518b455a87c1f3ac3a0d189c4466"
    CONTACT = "d7246a707f51ddf8b17ee2dddabd9e0a4da5c552"
    DOMAIN = "AppDomainGroup-group.net.whatsapp.WhatsAppSMB.shared"

class JidType(IntEnum):
    PM = 0
    GROUP = 1
    SYSTEM_BROADCAST = 5
    STATUS = 11
