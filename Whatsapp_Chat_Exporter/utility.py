import logging
import sqlite3
import jinja2
import json
import os
import unicodedata
import re
import string
import math
import shutil
from bleach import clean as sanitize
from markupsafe import Markup
from datetime import datetime, timedelta
from enum import IntEnum
from Whatsapp_Chat_Exporter.data_model import ChatCollection, ChatStore, Timing
from typing import Dict, List, Optional, Tuple, Union
try:
    from enum import StrEnum, IntEnum
except ImportError:
    # < Python 3.11
    # This should be removed when the support for Python 3.10 ends. (31 Oct 2026)
    from enum import Enum

    class StrEnum(str, Enum):
        pass

    class IntEnum(int, Enum):
        pass

MAX_SIZE = 4 * 1024 * 1024  # Default 4MB
ROW_SIZE = 0x3D0
CURRENT_TZ_OFFSET = datetime.now().astimezone().utcoffset().seconds / 3600
CLEAR_LINE = "\x1b[K\n"

logger = logging.getLogger(__name__)


def convert_time_unit(time_second: int) -> str:
    """Converts a time duration in seconds to a human-readable string.

    Args:
        time_second: The time duration in seconds.

    Returns:
        str: A human-readable string representing the time duration.
    """
    if time_second < 1:
        return "less than a second"
    elif time_second == 1:
        return "a second"

    delta = timedelta(seconds=time_second)
    parts = []

    days = delta.days
    if days > 0:
        parts.append(f"{days} day{'s' if days > 1 else ''}")

    hours = delta.seconds // 3600
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours > 1 else ''}")

    minutes = (delta.seconds % 3600) // 60
    if minutes > 0:
        parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")

    seconds = delta.seconds % 60
    if seconds > 0:
        parts.append(f"{seconds} second{'s' if seconds > 1 else ''}")

    return " ".join(parts)


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
    if size_bytes < 1024:
        return f"{size_bytes} B"
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
    if size_str.isnumeric():
        # If the string is purely numeric, assume it's in bytes
        return int(size_str)
    match = re.fullmatch(r'^(\d+(\.\d*)?)\s*([KMGTPEZY]?B)?$', size_str)
    if not match:
        raise ValueError("Invalid size format for size_str. Expected format like '10MB', '1024GB', or '512'.")
    unit = ''.join(filter(str.isalpha, size_str)).strip()
    number = ''.join(c for c in size_str if c.isdigit() or c == '.').strip()
    return int(float(number) * SIZE_UNITS[unit])


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
        logger.error("Failed to check for updates.")
        return 1
    else:
        with raw:
            package_info = json.load(raw)
            latest_version = tuple(
                map(int, package_info["info"]["version"].split(".")))
            __version__ = importlib.metadata.version("whatsapp_chat_exporter")
            current_version = tuple(map(int, __version__.split(".")))
            if current_version < latest_version:
                logger.info(
                    "===============Update===============\n"
                    "A newer version of WhatsApp Chat Exporter is available.\n"
                    f"Current version: {__version__}\n"
                    f"Latest version: {package_info['info']['version']}\n"
                )
                if platform == "win32":
                    logger.info("Update with: pip install --upgrade whatsapp-chat-exporter\n")
                else:
                    logger.info("Update with: pip3 install --upgrade whatsapp-chat-exporter\n")
                logger.info("====================================\n")
            else:
                logger.info("You are using the latest version of WhatsApp Chat Exporter.\n")
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


def import_from_json(json_file: str, data: ChatCollection):
    """Imports chat data from a JSON file into the data dictionary.

    Args:
        json_file: The path to the JSON file.
        data: The dictionary to store the imported chat data.
    """
    with open(json_file, "r") as f:
        temp_data = json.loads(f.read())
    total_row_number = len(tuple(temp_data.keys()))
    logger.info(f"Importing chats from JSON...(0/{total_row_number})\r")
    for index, (jid, chat_data) in enumerate(temp_data.items()):
        chat = ChatStore.from_json(chat_data)
        data.add_chat(jid, chat)
        logger.info(
            f"Importing chats from JSON...({index + 1}/{total_row_number})\r")
    logger.info(f"Imported {total_row_number} chats from JSON{CLEAR_LINE}")


def incremental_merge(source_dir: str, target_dir: str, media_dir: str, pretty_print_json: int, avoid_encoding_json: bool):
    """Merges JSON files from the source directory into the target directory.

    Args:
        source_dir (str): The path to the source directory containing JSON files.
        target_dir (str): The path to the target directory to merge into.
        media_dir (str): The path to the media directory.
    """
    json_files = [f for f in os.listdir(source_dir) if f.endswith('.json')]
    if not json_files:
        logger.error("No JSON files found in the source directory.")
        return

    logger.info("JSON files found:", json_files)

    for json_file in json_files:
        source_path = os.path.join(source_dir, json_file)
        target_path = os.path.join(target_dir, json_file)

        if not os.path.exists(target_path):
            logger.info(f"Copying '{json_file}' to target directory...")
            os.makedirs(target_dir, exist_ok=True)
            shutil.copy2(source_path, target_path)
        else:
            logger.info(
                f"Merging '{json_file}' with existing file in target directory...")
            with open(source_path, 'r') as src_file, open(target_path, 'r') as tgt_file:
                source_data = json.load(src_file)
                target_data = json.load(tgt_file)

                # Parse JSON into ChatStore objects using from_json()
                source_chats = {jid: ChatStore.from_json(
                    chat) for jid, chat in source_data.items()}
                target_chats = {jid: ChatStore.from_json(
                    chat) for jid, chat in target_data.items()}

                # Merge chats using merge_with()
                for jid, chat in source_chats.items():
                    if jid in target_chats:
                        target_chats[jid].merge_with(chat)
                    else:
                        target_chats[jid] = chat

                # Serialize merged data
                merged_data = {jid: chat.to_json()
                               for jid, chat in target_chats.items()}

                # Check if the merged data differs from the original target data
                if json.dumps(merged_data, sort_keys=True) != json.dumps(target_data, sort_keys=True):
                    logger.info(
                        f"Changes detected in '{json_file}', updating target file...")
                    with open(target_path, 'w') as merged_file:
                        json.dump(
                            merged_data,
                            merged_file,
                            indent=pretty_print_json,
                            ensure_ascii=not avoid_encoding_json,
                        )
                else:
                    logger.info(
                        f"No changes detected in '{json_file}', skipping update.")

    # Merge media directories
    source_media_path = os.path.join(source_dir, media_dir)
    target_media_path = os.path.join(target_dir, media_dir)
    logger.info(
        f"Merging media directories. Source: {source_media_path}, target: {target_media_path}")
    if os.path.exists(source_media_path):
        for root, _, files in os.walk(source_media_path):
            relative_path = os.path.relpath(root, source_media_path)
            target_root = os.path.join(target_media_path, relative_path)
            os.makedirs(target_root, exist_ok=True)
            for file in files:
                source_file = os.path.join(root, file)
                target_file = os.path.join(target_root, file)
                # we only copy if the file doesn't exist in the target or if the source is newer
                if not os.path.exists(target_file) or os.path.getmtime(source_file) > os.path.getmtime(target_file):
                    logger.info(f"Copying '{source_file}' to '{target_file}'...")
                    shutil.copy2(source_file, target_file)


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

    return safe_name(file_name), name


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
            raise ValueError(
                "There must be at least two elements in argument columns if jid is not None")
        if jid is not None:
            if platform == "android":
                is_group = f"{jid}.type == 1"
            elif platform == "ios":
                is_group = f"{jid} IS NOT NULL"
            else:
                raise ValueError(
                    "Only android and ios are supported for argument platform if jid is not None")
        for index, chat in enumerate(filter):
            if include:
                conditions.append(
                    f"{' OR' if index > 0 else ''} {columns[0]} LIKE '%{chat}%'")
                if len(columns) > 1:
                    conditions.append(
                        f" OR ({columns[1]} LIKE '%{chat}%' AND {is_group})")
            else:
                conditions.append(
                    f"{' AND' if index > 0 else ''} {columns[0]} NOT LIKE '%{chat}%'")
                if len(columns) > 1:
                    conditions.append(
                        f" AND ({columns[1]} NOT LIKE '%{chat}%' AND {is_group})")
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
    {"iv": 67, "db": 196}
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
        msg += (content['data'] or "Unknown").replace("\n", '<br>')
    elif content["action_type"] == 28:
        try:
            old = content['old_jid'].split('@')[0]
            new = content['new_jid'].split('@')[0]
        except (AttributeError, IndexError):
            return None
        else:
            msg = f"{old} changed their number to {new}"
    elif content["action_type"] == 46:
        return  # Voice message in PM??? Seems no need to handle.
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
        # (PM) this contact use secure service from Facebook??? What's the difference with 67????
        return
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
            with open(w3css_path, "wb") as f:
                f.write(resp.read())
    w3css = os.path.join(offline_static, "w3.css")
    return w3css


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


def safe_name(text: Union[str, bytes]) -> str:
    """
    Sanitize the input text and generates a safe file name.
    This function serves a similar purpose to slugify() from
    Django previously used in this project, but is a clean-room
    Reimplementation tailored for performance and a narrower
    Use case for this project. Licensed under the same terms
    As the project (MIT).

    Args:
        text (str|bytes): The string to be sanitized.

    Returns:
        str: The sanitized string with only alphanumerics, underscores, or hyphens.
    """
    if isinstance(text, bytes):
        text = text.decode("utf-8", "ignore")
    elif not isinstance(text, str):
        raise TypeError("value must be a string or bytes")
    normalized_text = unicodedata.normalize("NFKC", text)
    safe_chars = [char for char in normalized_text if char.isalnum() or char in "-_ ."]
    return "-".join(''.join(safe_chars).split())


def get_from_string(msg: Dict, chat_id: str) -> str:
    """Return the number or name for the sender"""
    if msg["from_me"]:
        return "Me"
    if msg["sender"]:
        return str(msg["sender"])
    return str(chat_id)


def get_chat_type(chat_id: str) -> str:
    """Return the chat type based on the whatsapp id"""
    if chat_id.endswith("@s.whatsapp.net"):
        return "personal_chat"
    if chat_id.endswith("@g.us"):
        return "private_group"
    logger.warning("Unknown chat type for %s, defaulting to private_group", chat_id)
    return "private_group"


def get_from_id(msg: Dict, chat_id: str) -> str:
    """Return the user id for the sender"""
    if msg["from_me"]:
        return "user00000"
    if msg["sender"]:
        return "user" + msg["sender"]
    return f"user{chat_id}"


def get_reply_id(data: Dict, reply_key: int) -> Optional[int]:
    """Get the id of the message corresponding to the reply"""
    if not reply_key:
        return None
    for msg_id, msg in data["messages"].items():
        if msg["key_id"] == reply_key:
            return msg_id
    return None


def telegram_json_format(jik: str, data: Dict, timezone_offset) -> Dict:
    """Convert the data to the Telegram export format"""
    timing = Timing(timezone_offset or CURRENT_TZ_OFFSET)
    try:
        chat_id = int(''.join([c for c in jik if c.isdigit()]))
    except ValueError:
        # not a real chat: e.g. statusbroadcast
        chat_id = 0
    obj = {
            "name": data["name"] if data["name"] else jik,
            "type": get_chat_type(jik),
            "id": chat_id,
            "messages": [ {
                "id": int(msgId),
                "type": "message",
                "date": timing.format_timestamp(msg["timestamp"], "%Y-%m-%dT%H:%M:%S"),
                "date_unixtime": int(msg["timestamp"]),
                "from": get_from_string(msg, chat_id),
                "from_id": get_from_id(msg, chat_id),
                "reply_to_message_id": get_reply_id(data, msg["reply"]),
                "text": msg["data"],
                "text_entities": [
                    {
                        # TODO this will lose formatting and different types
                        "type": "plain",
                        "text": msg["data"],
                        }
                    ],
                } for msgId, msg in data["messages"].items()]
            }
    # remove empty messages and replies
    for msg_id, msg in enumerate(obj["messages"]):
        if not msg["reply_to_message_id"]:
            del obj["messages"][msg_id]["reply_to_message_id"]
    obj["messages"] = [m for m in obj["messages"] if m["text"]]
    return obj


class WhatsAppIdentifier(StrEnum):
    # AppDomainGroup-group.net.whatsapp.WhatsApp.shared-ChatStorage.sqlite
    MESSAGE = "7c7fba66680ef796b916b067077cc246adacf01d"
    # AppDomainGroup-group.net.whatsapp.WhatsApp.shared-ContactsV2.sqlite
    CONTACT = "b8548dc30aa1030df0ce18ef08b882cf7ab5212f"
    # AppDomainGroup-group.net.whatsapp.WhatsApp.shared-CallHistory.sqlite
    CALL = "1b432994e958845fffe8e2f190f26d1511534088"
    DOMAIN = "AppDomainGroup-group.net.whatsapp.WhatsApp.shared"


class WhatsAppBusinessIdentifier(StrEnum):
    # AppDomainGroup-group.net.whatsapp.WhatsAppSMB.shared-ChatStorage.sqlite
    MESSAGE = "724bd3b98b18518b455a87c1f3ac3a0d189c4466"
    # AppDomainGroup-group.net.whatsapp.WhatsAppSMB.shared-ContactsV2.sqlite
    CONTACT = "d7246a707f51ddf8b17ee2dddabd9e0a4da5c552"
    # AppDomainGroup-group.net.whatsapp.WhatsAppSMB.shared-CallHistory.sqlite
    CALL = "b463f7c4365eefc5a8723930d97928d4e907c603"
    DOMAIN = "AppDomainGroup-group.net.whatsapp.WhatsAppSMB.shared"


class JidType(IntEnum):
    PM = 0
    GROUP = 1
    SYSTEM_BROADCAST = 5
    STATUS = 11
