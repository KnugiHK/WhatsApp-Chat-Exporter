import sqlite3
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
from typing import Dict, List, Optional, Tuple
try:
    from enum import StrEnum, IntEnum
except ImportError:
    # < Python 3.11
    # This should be removed when the support for Python 3.10 ends.
    from enum import Enum
    class StrEnum(str, Enum):
        pass

    class IntEnum(int, Enum):
        pass

MAX_SIZE = 4 * 1024 * 1024  # Default 4MB
ROW_SIZE = 0x3D0
CURRENT_TZ_OFFSET = datetime.now().astimezone().utcoffset().seconds / 3600


def convert_time_unit(time_second: int) -> str:
    """Converts a time duration in seconds to a human-readable string.

    Args:
        time_second: The time duration in seconds.

    Returns:
        str: A human-readable string representing the time duration.
    """
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


def bytes_to_readable(size_bytes: int) -> str:
    """Converts a file size in bytes to a human-readable string with units.

    From https://stackoverflow.com/a/14822210/9478891
    Authors: james-sapam & other contributors
    Licensed under CC BY-SA 3.0
    See git commit logs for changes, if any.

    Args:
        size_bytes: The file size in bytes.

    Returns:
        A human-readable string representing the file size.
    """
    if size_bytes == 0:
       return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return "%s %s" % (s, size_name[i])


def readable_to_bytes(size_str: str) -> int:
    """Converts a human-readable file size string to bytes.

    Args:
        size_str: The human-readable file size string (e.g., "1024KB", "1MB", "2GB").

    Returns:
        The file size in bytes.

    Raises:
        ValueError: If the input string is invalid.
    """
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


def sanitize_except(html: str) -> Markup:
    """Sanitizes HTML, only allowing <br> tag.

    Args:
        html: The HTML string to sanitize.

    Returns:
        A Markup object containing the sanitized HTML.
    """
    return Markup(sanitize(html, tags=["br"]))


def determine_day(last: int, current: int) -> Optional[datetime.date]:
    """Determines if the day has changed between two timestamps. Exposed to Jinja's environment.

    Args:
        last: The timestamp of the previous message.
        current: The timestamp of the current message.

    Returns:
        The date of the current message if it's a different day than the last message, otherwise None.
    """
    last = datetime.fromtimestamp(last).date()
    current = datetime.fromtimestamp(current).date()
    if last == current:
        return None
    else:
        return current


def check_update():
    import urllib.request
    import json
    import importlib
    from sys import platform

    PACKAGE_JSON = "https://pypi.org/pypi/whatsapp-chat-exporter/json"
    try:
        raw = urllib.request.urlopen(PACKAGE_JSON)
    except Exception:
        print("Failed to check for updates.")
        return 1
    else:
        with raw:
            package_info = json.load(raw)
            latest_version = tuple(map(int, package_info["info"]["version"].split(".")))
            __version__ = importlib.metadata.version("whatsapp_chat_exporter")
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
        chat,
        headline,
        next=False,
        previous=False
    ):
    if chat.their_avatar_thumb is None and chat.their_avatar is not None:
        their_avatar_thumb = chat.their_avatar
    else:
        their_avatar_thumb = chat.their_avatar_thumb
    if "??" not in headline:
        raise ValueError("Headline must contain '??' to replace with name")
    headline = headline.replace("??", name)
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
                previous=previous,
                status=chat.status,
                media_base=chat.media_base,
                headline=headline
            )
        )


class Device(StrEnum):
    IOS = "ios"
    ANDROID = "android"
    EXPORTED = "exported"


def import_from_json(json_file: str, data: Dict[str, ChatStore]):
    """Imports chat data from a JSON file into the data dictionary.

    Args:
        json_file: The path to the JSON file.
        data: The dictionary to store the imported chat data.
    """
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
                from_me=msg["from_me"],
                timestamp=msg["timestamp"],
                time=msg["time"],
                key_id=msg["key_id"],
                received_timestamp=msg.get("received_timestamp"),
                read_timestamp=msg.get("read_timestamp")
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


def sanitize_filename(file_name: str) -> str:
    """Sanitizes a filename by removing invalid and unsafe characters.

    Args:
        file_name: The filename to sanitize.

    Returns:
        The sanitized filename.
    """
    return "".join(x for x in file_name if x.isalnum() or x in "- ")


def get_file_name(contact: str, chat: ChatStore) -> Tuple[str, str]:
    """Generates a sanitized filename and contact name for a chat.

    Args:
        contact: The contact identifier (e.g., a phone number or group ID).
        chat: The ChatStore object for the chat.

    Returns:
        A tuple containing the sanitized filename and the contact name.

    Raises:
        ValueError: If the contact format is unexpected.
    """
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


def get_cond_for_empty(enable: bool, jid_field: str, broadcast_field: str) -> str:
    """Generates a SQL condition for filtering empty chats.

    Args:
        enable: True to include non-empty chats, False to include empty chats.
        jid_field: The name of the JID field in the SQL query.
        broadcast_field: The column name of the broadcast field in the SQL query.

    Returns:
        A SQL condition string.
    """
    return f"AND (chat.hidden=0 OR {jid_field}='status@broadcast' OR {broadcast_field}>0)" if enable else ""


def get_chat_condition(filter: Optional[List[str]], include: bool, columns: List[str], jid: Optional[str] = None, platform: Optional[str] = None) -> str:
    """Generates a SQL condition for filtering chats based on inclusion or exclusion criteria.

    Args:
        filter: A list of phone numbers to include or exclude.
        include: True to include chats that match the filter, False to exclude them.
        columns: A list of column names to check against the filter.
        jid: The JID column name (used for group identification).
        platform: The platform ("android" or "ios") for platform-specific JID queries.

    Returns:
        A SQL condition string.

    Raises:
        ValueError: If the column count is invalid or an unsupported platform is provided.
    """
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


# Android Specific
CRYPT14_OFFSETS = (
    {"iv": 67, "db": 191},
    {"iv": 67, "db": 190},
    {"iv": 66, "db": 99},
    {"iv": 67, "db": 193},
    {"iv": 67, "db": 194},
    {"iv": 67, "db": 158},
)


class Crypt(IntEnum):
    CRYPT15 = 15
    CRYPT14 = 14
    CRYPT12 = 12


class DbType(StrEnum):
    MESSAGE = "message"
    CONTACT = "contact"


def determine_metadata(content: sqlite3.Row, init_msg: Optional[str]) -> Optional[str]:
    """Determines the metadata of a message.

    Args:
        content (sqlite3.Row): A row from the messages table.
        init_msg (Optional[str]): The initial message, if any.

    Returns:
        The metadata as a string or None if the type is unsupported.
    """
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


def get_status_location(output_folder: str, offline_static: str) -> str:
    """
    Gets the location of the W3.CSS file, either from web or local storage.

    Args:
        output_folder (str): The folder where offline static files will be stored.
        offline_static (str): The subfolder name for static files. If falsy, returns web URL.

    Returns:
        str: The path or URL to the W3.CSS file.
    """
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


def setup_template(template: Optional[str], no_avatar: bool, experimental: bool = False) -> jinja2.Template:
    """
    Sets up the Jinja2 template environment and loads the template.

    Args:
        template (Optional[str]): Path to custom template file. If None, uses default template.
        no_avatar (bool): Whether to disable avatar display in the template.
        experimental (bool, optional): Whether to use experimental template features. Defaults to False.

    Returns:
        jinja2.Template: The configured Jinja2 template object.
    """
    if template is None or experimental:
        template_dir = os.path.dirname(__file__)
        template_file = "whatsapp.html" if not experimental else template
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
APPLE_TIME = 978307200


def slugify(value: str, allow_unicode: bool = False) -> str:
    """
    Convert text to ASCII-only slugs for URL-safe strings.
    Taken from https://github.com/django/django/blob/master/django/utils/text.py

    Args:
        value (str): The string to convert to a slug.
        allow_unicode (bool, optional): Whether to allow Unicode characters. Defaults to False.

    Returns:
        str: The slugified string with only alphanumerics, underscores, or hyphens.
    """
    value = str(value)
    if allow_unicode:
        value = unicodedata.normalize('NFKC', value)
    else:
        value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^\w\s-]', '', value.lower())
    return re.sub(r'[-\s]+', '-', value).strip('-_')


class WhatsAppIdentifier(StrEnum):
    MESSAGE = "7c7fba66680ef796b916b067077cc246adacf01d" # AppDomainGroup-group.net.whatsapp.WhatsApp.shared-ChatStorage.sqlite
    CONTACT = "b8548dc30aa1030df0ce18ef08b882cf7ab5212f" # AppDomainGroup-group.net.whatsapp.WhatsApp.shared-ContactsV2.sqlite
    CALL = "1b432994e958845fffe8e2f190f26d1511534088" # AppDomainGroup-group.net.whatsapp.WhatsApp.shared-CallHistory.sqlite
    DOMAIN = "AppDomainGroup-group.net.whatsapp.WhatsApp.shared"


class WhatsAppBusinessIdentifier(StrEnum):
    MESSAGE = "724bd3b98b18518b455a87c1f3ac3a0d189c4466" # AppDomainGroup-group.net.whatsapp.WhatsAppSMB.shared-ChatStorage.sqlite
    CONTACT = "d7246a707f51ddf8b17ee2dddabd9e0a4da5c552" # AppDomainGroup-group.net.whatsapp.WhatsAppSMB.shared-ContactsV2.sqlite
    CALL = "b463f7c4365eefc5a8723930d97928d4e907c603" # AppDomainGroup-group.net.whatsapp.WhatsAppSMB.shared-CallHistory.sqlite
    DOMAIN = "AppDomainGroup-group.net.whatsapp.WhatsAppSMB.shared" 

class JidType(IntEnum):
    PM = 0
    GROUP = 1
    SYSTEM_BROADCAST = 5
    STATUS = 11
