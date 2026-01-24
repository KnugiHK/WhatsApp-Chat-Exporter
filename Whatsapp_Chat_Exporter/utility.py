import logging
import sqlite3
import jinja2
import json
import os
import unicodedata
import re
import math
import shutil
from bleach import clean as sanitize
from markupsafe import Markup
from datetime import datetime, timedelta
from enum import IntEnum
from tqdm import tqdm
from Whatsapp_Chat_Exporter.data_model import ChatCollection, ChatStore, Timing
from typing import Dict, List, Optional, Tuple, Union, Any
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


def check_update(include_beta: bool = False) -> int:
    import urllib.request
    import json
    import importlib
    from sys import platform
    from packaging import version

    PACKAGE_JSON = "https://pypi.org/pypi/whatsapp-chat-exporter/json"
    try:
        raw = urllib.request.urlopen(PACKAGE_JSON)
    except Exception:
        logging.error("Failed to check for updates.")
        return 1
    else:
        with raw:
            package_info = json.load(raw)
            if include_beta:
                all_versions = [version.parse(v) for v in package_info["releases"].keys()]
                latest_version = max(all_versions, key=lambda v: (v.release, v.pre))
            else:
                latest_version = version.parse(package_info["info"]["version"])
            current_version = version.parse(importlib.metadata.version("whatsapp_chat_exporter"))
            if current_version < latest_version:
                logging.info(
                    "===============Update===============\n"
                    "A newer version of WhatsApp Chat Exporter is available.\n"
                    f"Current version: {current_version}\n"
                    f"Latest version: {latest_version}"
                )
                pip_cmd = "pip" if platform == "win32" else "pip3"
                logging.info(f"Update with: {pip_cmd} install --upgrade whatsapp-chat-exporter {'--pre' if include_beta else ''}")
                logging.info("====================================")
            else:
                logging.info("You are using the latest version of WhatsApp Chat Exporter.")
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
    with tqdm(total=total_row_number, desc="Importing chats from JSON", unit="chat", leave=False) as pbar:
        for jid, chat_data in temp_data.items():
            chat = ChatStore.from_json(chat_data)
            data.add_chat(jid, chat)
            pbar.update(1)
        total_time = pbar.format_dict['elapsed']
    logging.info(f"Imported {total_row_number} chats from JSON in {convert_time_unit(total_time)}")


class IncrementalMerger:
    """Handles incremental merging of WhatsApp chat exports."""
    
    def __init__(self, pretty_print_json: int, avoid_encoding_json: bool):
        """Initialize the merger with JSON formatting options.
        
        Args:
            pretty_print_json: JSON indentation level.
            avoid_encoding_json: Whether to avoid ASCII encoding.
        """
        self.pretty_print_json = pretty_print_json
        self.avoid_encoding_json = avoid_encoding_json
    
    def _get_json_files(self, source_dir: str) -> List[str]:
        """Get list of JSON files from source directory.
        
        Args:
            source_dir: Path to the source directory.
            
        Returns:
            List of JSON filenames.
            
        Raises:
            SystemExit: If no JSON files are found.
        """
        json_files = [f for f in os.listdir(source_dir) if f.endswith('.json')]
        if not json_files:
            logging.error("No JSON files found in the source directory.")
            raise SystemExit(1)
        
        logging.debug("JSON files found:", json_files)
        return json_files

    def _copy_new_file(self, source_path: str, target_path: str, target_dir: str, json_file: str) -> None:
        """Copy a new JSON file to target directory.
        
        Args:
            source_path: Path to source file.
            target_path: Path to target file.
            target_dir: Target directory path.
            json_file: Name of the JSON file.
        """
        logging.info(f"Copying '{json_file}' to target directory...")
        os.makedirs(target_dir, exist_ok=True)
        shutil.copy2(source_path, target_path)

    def _load_chat_data(self, file_path: str) -> Dict[str, Any]:
        """Load JSON data from file.
        
        Args:
            file_path: Path to JSON file.
            
        Returns:
            Loaded JSON data.
        """
        with open(file_path, 'r') as file:
            return json.load(file)

    def _parse_chats_from_json(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse JSON data into ChatStore objects.
        
        Args:
            data: Raw JSON data.
            
        Returns:
            Dictionary of JID to ChatStore objects.
        """
        return {jid: ChatStore.from_json(chat) for jid, chat in data.items()}

    def _merge_chat_stores(self, source_chats: Dict[str, Any], target_chats: Dict[str, Any]) -> Dict[str, Any]:
        """Merge source chats into target chats.
        
        Args:
            source_chats: Source ChatStore objects.
            target_chats: Target ChatStore objects.
            
        Returns:
            Merged ChatStore objects.
        """
        for jid, chat in source_chats.items():
            if jid in target_chats:
                target_chats[jid].merge_with(chat)
            else:
                target_chats[jid] = chat
        return target_chats

    def _serialize_chats(self, chats: Dict[str, Any]) -> Dict[str, Any]:
        """Serialize ChatStore objects to JSON format.
        
        Args:
            chats: Dictionary of ChatStore objects.
            
        Returns:
            Serialized JSON data.
        """
        return {jid: chat.to_json() for jid, chat in chats.items()}

    def _has_changes(self, merged_data: Dict[str, Any], original_data: Dict[str, Any]) -> bool:
        """Check if merged data differs from original data.
        
        Args:
            merged_data: Merged JSON data.
            original_data: Original JSON data.
            
        Returns:
            True if changes detected, False otherwise.
        """
        return json.dumps(merged_data, sort_keys=True) != json.dumps(original_data, sort_keys=True)

    def _save_merged_data(self, target_path: str, merged_data: Dict[str, Any]) -> None:
        """Save merged data to target file.
        
        Args:
            target_path: Path to target file.
            merged_data: Merged JSON data.
        """
        with open(target_path, 'w') as merged_file:
            json.dump(
                merged_data,
                merged_file,
                indent=self.pretty_print_json,
                ensure_ascii=not self.avoid_encoding_json,
            )

    def _merge_json_file(self, source_path: str, target_path: str, json_file: str) -> None:
        """Merge a single JSON file.
        
        Args:
            source_path: Path to source file.
            target_path: Path to target file.
            json_file: Name of the JSON file.
        """
        logging.info(f"Merging '{json_file}' with existing file in target directory...", extra={"clear": True})
        
        source_data = self._load_chat_data(source_path)
        target_data = self._load_chat_data(target_path)
        
        source_chats = self._parse_chats_from_json(source_data)
        target_chats = self._parse_chats_from_json(target_data)
        
        merged_chats = self._merge_chat_stores(source_chats, target_chats)
        merged_data = self._serialize_chats(merged_chats)
        
        if self._has_changes(merged_data, target_data):
            logging.info(f"Changes detected in '{json_file}', updating target file...")
            self._save_merged_data(target_path, merged_data)
        else:
            logging.info(f"No changes detected in '{json_file}', skipping update.")

    def _should_copy_media_file(self, source_file: str, target_file: str) -> bool:
        """Check if media file should be copied.
        
        Args:
            source_file: Path to source media file.
            target_file: Path to target media file.
            
        Returns:
            True if file should be copied, False otherwise.
        """
        return not os.path.exists(target_file) or os.path.getmtime(source_file) > os.path.getmtime(target_file)

    def _merge_media_directories(self, source_dir: str, target_dir: str, media_dir: str) -> None:
        """Merge media directories from source to target.
        
        Args:
            source_dir: Source directory path.
            target_dir: Target directory path.
            media_dir: Media directory name.
        """
        source_media_path = os.path.join(source_dir, media_dir)
        target_media_path = os.path.join(target_dir, media_dir)
        
        logging.info(f"Merging media directories. Source: {source_media_path}, target: {target_media_path}")
        
        if not os.path.exists(source_media_path):
            return
        
        for root, _, files in os.walk(source_media_path):
            relative_path = os.path.relpath(root, source_media_path)
            target_root = os.path.join(target_media_path, relative_path)
            os.makedirs(target_root, exist_ok=True)
            
            for file in files:
                source_file = os.path.join(root, file)
                target_file = os.path.join(target_root, file)
                
                if self._should_copy_media_file(source_file, target_file):
                    logging.debug(f"Copying '{source_file}' to '{target_file}'...")
                    shutil.copy2(source_file, target_file)

    def merge(self, source_dir: str, target_dir: str, media_dir: str) -> None:
        """Merge JSON files and media from source to target directory.
        
        Args:
            source_dir: The path to the source directory containing JSON files.
            target_dir: The path to the target directory to merge into.
            media_dir: The path to the media directory.
        """
        json_files = self._get_json_files(source_dir)
        
        logging.info("Starting incremental merge process...")
        for json_file in json_files:
            source_path = os.path.join(source_dir, json_file)
            target_path = os.path.join(target_dir, json_file)
            
            if not os.path.exists(target_path):
                self._copy_new_file(source_path, target_path, target_dir, json_file)
            else:
                self._merge_json_file(source_path, target_path, json_file)
        
        self._merge_media_directories(source_dir, target_dir, media_dir)


def incremental_merge(source_dir: str, target_dir: str, media_dir: str, pretty_print_json: int, avoid_encoding_json: bool) -> None:
    """Wrapper for merging JSON files from the source directory into the target directory.

    Args:
        source_dir: The path to the source directory containing JSON files.
        target_dir: The path to the target directory to merge into.
        media_dir: The path to the media directory.
        pretty_print_json: JSON indentation level.
        avoid_encoding_json: Whether to avoid ASCII encoding.
    """
    merger = IncrementalMerger(pretty_print_json, avoid_encoding_json)
    merger.merge(source_dir, target_dir, media_dir)


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


def _get_group_condition(jid: str, platform: str) -> str:
    """Generate platform-specific group identification condition.
    
    Args:
        jid: The JID column name.
        platform: The platform ("android" or "ios").
        
    Returns:
        SQL condition string for group identification.
        
    Raises:
        ValueError: If platform is not supported.
    """
    if platform == "android":
        return f"{jid}.type == 1"
    elif platform == "ios":
        return f"{jid} IS NOT NULL"
    else:
        raise ValueError(
            "Only android and ios are supported for argument platform if jid is not None")


def get_chat_condition(
    filter: Optional[List[str]],
    include: bool,
    columns: List[str],
    jid: Optional[str] = None,
    platform: Optional[str] = None
) -> str:
    """Generates a SQL condition for filtering chats based on inclusion or exclusion criteria.

    SQL injection risks from chat filters were evaluated during development and deemed negligible
    due to the tool's offline, trusted-input model (user running this tool on WhatsApp
    backups/databases on their own device).

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
    if not filter:
        return ""
    
    if jid is not None and len(columns) < 2:
        raise ValueError(
            "There must be at least two elements in argument columns if jid is not None")

    # Get group condition if needed
    is_group_condition = None
    if jid is not None:
        is_group_condition = _get_group_condition(jid, platform)

    # Build conditions for each chat filter
    conditions = []
    for index, chat in enumerate(filter):
        # Add connector for subsequent conditions (with double space)
        connector = " OR" if include else " AND"
        prefix = connector if index > 0 else ""

        # Primary column condition
        operator = "LIKE" if include else "NOT LIKE"
        conditions.append(f"{prefix} {columns[0]} {operator} '%{chat}%'")

        # Secondary column condition for groups
        if len(columns) > 1 and is_group_condition:
            if include:
                group_condition = f" OR ({columns[1]} {operator} '%{chat}%' AND {is_group_condition})" 
            else:
                group_condition = f" AND ({columns[1]} {operator} '%{chat}%' AND {is_group_condition})"
            conditions.append(group_condition)

    combined_conditions = "".join(conditions)
    return f"AND ({combined_conditions})"


# Android Specific
CRYPT14_OFFSETS = (
    {"iv": 67, "db": 191},
    {"iv": 67, "db": 190},
    {"iv": 66, "db": 99},
    {"iv": 67, "db": 193},
    {"iv": 67, "db": 194},
    {"iv": 67, "db": 158},
    {"iv": 67, "db": 196},
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
        msg = "You blocked/unblocked this contact"
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


def check_jid_map(db: sqlite3.Connection) -> bool:
    """
    Checks if the jid_map table exists in the database.

    Args:
        db (sqlite3.Connection): The SQLite database connection.

    Returns:
        bool: True if the jid_map table exists, False otherwise.
    """
    cursor = db.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jid_map'")
    return cursor.fetchone() is not None


def get_jid_map_join(jid_map_exists: bool) -> str:
    """
    Returns the SQL JOIN statements for jid_map table.
    """
    if not jid_map_exists:
        return ""
    else:
        return """LEFT JOIN jid_map as jid_map_global
                    ON chat.jid_row_id = jid_map_global.lid_row_id
                LEFT JOIN jid lid_global
                    ON jid_map_global.jid_row_id = lid_global._id
                LEFT JOIN jid_map as jid_map_group
                    ON message.sender_jid_row_id = jid_map_group.lid_row_id
                LEFT JOIN jid lid_group
                    ON jid_map_group.jid_row_id = lid_group._id"""

def get_jid_map_selection(jid_map_exists: bool) -> tuple:
    """
    Returns the SQL selection statements for jid_map table.
    """
    if not jid_map_exists:
        return "jid_global.raw_string", "jid_group.raw_string"
    else:
        return (
            "COALESCE(lid_global.raw_string, jid_global.raw_string)",
            "COALESCE(lid_group.raw_string, jid_group.raw_string)"
        )
        

def get_transcription_selection(db: sqlite3.Connection) -> str:
    """
    Returns the SQL selection statement for transcription text based on the database schema.

    Args:
        db (sqlite3.Connection): The SQLite database connection.
    Returns:
        str: The SQL selection statement for transcription.
    """
    cursor = db.cursor()
    cursor.execute("PRAGMA table_info(message_media)")
    columns = [row[1] for row in cursor.fetchall()]

    if "raw_transcription_text" in columns:
        return "message_media.raw_transcription_text AS transcription_text"
    else:
        return "NULL AS transcription_text"


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
    if chat_id == "000000000000000":
        return "calls"
    elif chat_id.endswith("@s.whatsapp.net"):
        return "personal_chat"
    elif chat_id.endswith("@g.us"):
        return "private_group"
    elif chat_id == "status@broadcast":
        return "status_broadcast"
    elif chat_id.endswith("@broadcast"):
        return "broadcast_channel"
    logging.warning(f"Unknown chat type for {chat_id}, defaulting to private_group")
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
    json_obj = {
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
            }
        for msgId, msg in data["messages"].items()]
    }
    # remove empty messages and replies
    for msg_id, msg in enumerate(json_obj["messages"]):
        if not msg["reply_to_message_id"]:
            del json_obj["messages"][msg_id]["reply_to_message_id"]
    json_obj["messages"] = [m for m in json_obj["messages"] if m["text"]]
    return json_obj


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
