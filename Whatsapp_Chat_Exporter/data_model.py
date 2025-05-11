import os
from datetime import datetime, tzinfo, timedelta
from typing import MutableMapping, Union, Optional, Dict, Any


class Timing:
    """
    Handles timestamp formatting with timezone support.
    """

    def __init__(self, timezone_offset: Optional[int]) -> None:
        """
        Initialize Timing object.

        Args:
            timezone_offset (Optional[int]): Hours offset from UTC
        """
        self.timezone_offset = timezone_offset

    def format_timestamp(self, timestamp: Optional[Union[int, float]], format: str) -> Optional[str]:
        """
        Format a timestamp with the specified format string.

        Args:
            timestamp (Optional[Union[int, float]]): Unix timestamp to format
            format (str): strftime format string

        Returns:
            Optional[str]: Formatted timestamp string, or None if timestamp is None
        """
        if timestamp is not None:
            timestamp = timestamp / 1000 if timestamp > 9999999999 else timestamp
            return datetime.fromtimestamp(timestamp, TimeZone(self.timezone_offset)).strftime(format)
        return None


class TimeZone(tzinfo):
    """
    Custom timezone class with fixed offset.
    """

    def __init__(self, offset: int) -> None:
        """
        Initialize TimeZone object.

        Args:
            offset (int): Hours offset from UTC
        """
        self.offset = offset

    def utcoffset(self, dt: Optional[datetime]) -> timedelta:
        """Get UTC offset."""
        return timedelta(hours=self.offset)

    def dst(self, dt: Optional[datetime]) -> timedelta:
        """Get DST offset (always 0)."""
        return timedelta(0)


class ChatCollection(MutableMapping):
    """
    A collection of chats that provides dictionary-like access with additional chat management methods.
    Inherits from MutableMapping to implement a custom dictionary-like behavior.
    """

    def __init__(self) -> None:
        """Initialize an empty chat collection."""
        self._chats: Dict[str, ChatStore] = {}

    def __getitem__(self, key: str) -> 'ChatStore':
        """Get a chat by its ID. Required for dict-like access."""
        return self._chats[key]

    def __setitem__(self, key: str, value: 'ChatStore') -> None:
        """Set a chat by its ID. Required for dict-like access."""
        if not isinstance(value, ChatStore):
            raise TypeError("Value must be a ChatStore object")
        self._chats[key] = value

    def __delitem__(self, key: str) -> None:
        """Delete a chat by its ID. Required for dict-like access."""
        del self._chats[key]

    def __iter__(self):
        """Iterate over chat IDs. Required for dict-like access."""
        return iter(self._chats)

    def __len__(self) -> int:
        """Get number of chats. Required for dict-like access."""
        return len(self._chats)

    def get_chat(self, chat_id: str) -> Optional['ChatStore']:
        """
        Get a chat by its ID.

        Args:
            chat_id (str): The ID of the chat to retrieve

        Returns:
            Optional['ChatStore']: The chat if found, None otherwise
        """
        return self._chats.get(chat_id)

    def add_chat(self, chat_id: str, chat: 'ChatStore') -> None:
        """
        Add a new chat to the collection.

        Args:
            chat_id (str): The ID for the chat
            chat (ChatStore): The chat to add

        Raises:
            TypeError: If chat is not a ChatStore object
        """
        if not isinstance(chat, ChatStore):
            raise TypeError("Chat must be a ChatStore object")
        self._chats[chat_id] = chat
        return self._chats[chat_id]

    def remove_chat(self, chat_id: str) -> None:
        """
        Remove a chat from the collection.

        Args:
            chat_id (str): The ID of the chat to remove
        """
        if chat_id in self._chats:
            del self._chats[chat_id]

    def items(self):
        """Get chat items (id, chat) pairs."""
        return self._chats.items()

    def values(self):
        """Get all chats."""
        return self._chats.values()

    def keys(self):
        """Get all chat IDs."""
        return self._chats.keys()

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the collection to a dictionary.

        Returns:
            Dict[str, Any]: Dictionary representation of all chats
        """
        return {chat_id: chat.to_json() for chat_id, chat in self._chats.items()}


class ChatStore:
    """
    Stores chat information and messages.
    """

    def __init__(self, type: str, name: Optional[str] = None, media: Optional[str] = None) -> None:
        """
        Initialize ChatStore object.

        Args:
            type (str): Device type (IOS or ANDROID)
            name (Optional[str]): Chat name
            media (Optional[str]): Path to media folder

        Raises:
            TypeError: If name is not a string or None
        """
        if name is not None and not isinstance(name, str):
            raise TypeError("Name must be a string or None")
        self.name = name
        self._messages: Dict[str, 'Message'] = {}
        self.type = type
        if media is not None:
            from Whatsapp_Chat_Exporter.utility import Device
            if self.type == Device.IOS:
                self.my_avatar = os.path.join(media, "Media/Profile/Photo.jpg")
            elif self.type == Device.ANDROID:
                self.my_avatar = None  # TODO: Add Android support
            else:
                self.my_avatar = None
        else:
            self.my_avatar = None
        self.their_avatar = None
        self.their_avatar_thumb = None
        self.status = None
        self.media_base = ""

    def __len__(self) -> int:
        """Get number of chats. Required for dict-like access."""
        return len(self._messages)

    def add_message(self, id: str, message: 'Message') -> None:
        """Add a message to the chat store."""
        if not isinstance(message, Message):
            raise TypeError("message must be a Message object")
        self._messages[id] = message

    def get_message(self, id: str) -> 'Message':
        """Get a message from the chat store."""
        return self._messages.get(id)

    def delete_message(self, id: str) -> None:
        """Delete a message from the chat store."""
        if id in self._messages:
            del self._messages[id]

    def to_json(self) -> Dict[str, Any]:
        """Convert chat store to JSON-serializable dict."""
        json_dict = {
            key: value
            for key, value in self.__dict__.items()
            if key != '_messages'
        }
        json_dict['messages'] = {id: msg.to_json() for id, msg in self._messages.items()}
        return json_dict

    @classmethod
    def from_json(cls, data: Dict) -> 'ChatStore':
        """Create a chat store from JSON data."""
        chat = cls(data.get("type"), data.get("name"))
        for key, value in data.items():
            if hasattr(chat, key) and key not in ("messages", "type", "name"):
                setattr(chat, key, value)
        for id, msg_data in data.get("messages", {}).items():
            message = Message.from_json(msg_data)
            chat.add_message(id, message)
        return chat

    def get_last_message(self) -> 'Message':
        """Get the most recent message in the chat."""
        return tuple(self._messages.values())[-1]

    def items(self):
        """Get message items pairs."""
        return self._messages.items()

    def values(self):
        """Get all messages in the chat."""
        return self._messages.values()

    def keys(self):
        """Get all message keys in the chat."""
        return self._messages.keys()

    def merge_with(self, other: 'ChatStore'):
        """Merge another ChatStore into this one.

        Args:
            other (ChatStore): The ChatStore to merge with

        """
        if not isinstance(other, ChatStore):
            raise TypeError("Can only merge with another ChatStore object")

        # Update fields if they are not None in the other ChatStore
        self.name = other.name or self.name
        self.type = other.type or self.type
        self.my_avatar = other.my_avatar or self.my_avatar
        self.their_avatar = other.their_avatar or self.their_avatar
        self.their_avatar_thumb = other.their_avatar_thumb or self.their_avatar_thumb
        self.status = other.status or self.status

        # Merge messages
        self._messages.update(other._messages)


class Message:
    """
    Represents a single message in a chat.
    """

    def __init__(
            self,
            *,
            from_me: Union[bool, int],
            timestamp: int,
            time: Union[int, float, str],
            key_id: Union[int, str],
            received_timestamp: int = None,
            read_timestamp: int = None,
            timezone_offset: int = 0,
            message_type: Optional[int] = None
    ) -> None:
        """
        Initialize Message object.

        Args:
            from_me (Union[bool, int]): Whether message was sent by the user
            timestamp (int): Message timestamp
            time (Union[int, float, str]): Message time
            key_id (int): Message unique identifier
            received_timestamp (int, optional): When message was received. Defaults to None
            read_timestamp (int, optional): When message was read. Defaults to None
            timezone_offset (int, optional): Hours offset from UTC. Defaults to 0
            message_type (Optional[int], optional): Type of message. Defaults to None

        Raises:
            TypeError: If time is not a string or number
        """
        self.from_me = bool(from_me)
        self.timestamp = timestamp / 1000 if timestamp > 9999999999 else timestamp
        timing = Timing(timezone_offset)

        if isinstance(time, (int, float)):
            self.time = timing.format_timestamp(self.timestamp, "%H:%M")
        elif isinstance(time, str):
            self.time = time
        else:
            raise TypeError("Time must be a string or number")

        self.media = False
        self.key_id = key_id
        self.meta = False
        self.data = None
        self.sender = None
        self.safe = False
        self.mime = None
        self.message_type = message_type
        if isinstance(received_timestamp, (int, float)):
            self.received_timestamp = timing.format_timestamp(
                received_timestamp, "%Y/%m/%d %H:%M")
        elif isinstance(received_timestamp, str):
            self.received_timestamp = received_timestamp
        else:
            self.received_timestamp = None
        if isinstance(read_timestamp, (int, float)):
            self.read_timestamp = timing.format_timestamp(
                read_timestamp, "%Y/%m/%d %H:%M")
        elif isinstance(read_timestamp, str):
            self.read_timestamp = read_timestamp
        else:
            self.read_timestamp = None

        # Extra attributes
        self.reply = None
        self.quoted_data = None
        self.caption = None
        self.thumb = None  # Android specific
        self.sticker = False

    def to_json(self) -> Dict[str, Any]:
        """Convert message to JSON-serializable dict."""
        return {
            key: value
            for key, value in self.__dict__.items()
        }

    @classmethod
    def from_json(cls, data: Dict) -> 'Message':
        message = cls(
            from_me=data["from_me"],
            timestamp=data["timestamp"],
            time=data["time"],
            key_id=data["key_id"],
            message_type=data.get("message_type"),
            received_timestamp=data.get("received_timestamp"),
            read_timestamp=data.get("read_timestamp")
        )
        added = ("from_me", "timestamp", "time", "key_id", "message_type",
                 "received_timestamp", "read_timestamp")
        for key, value in data.items():
            if hasattr(message, key) and key not in added:
                setattr(message, key, value)
        return message
