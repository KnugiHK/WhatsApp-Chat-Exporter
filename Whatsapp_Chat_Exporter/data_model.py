import os
from datetime import datetime, tzinfo, timedelta
from typing import Union, Optional, Dict, Any


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
        if timestamp:
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
        return {
            'name': self.name,
            'type': self.type,
            'my_avatar': self.my_avatar,
            'their_avatar': self.their_avatar,
            'their_avatar_thumb': self.their_avatar_thumb,
            'status': self.status,
            'messages': {id: msg.to_json() for id, msg in self._messages.items()}
        }

    def get_last_message(self) -> 'Message':
        """Get the most recent message in the chat."""
        return tuple(self._messages.values())[-1]

    def get_messages(self) -> Dict[str, 'Message']:
        """Get all messages in the chat."""
        return self._messages.values()


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
            key_id: int,
            received_timestamp: int,
            read_timestamp: int,
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
            received_timestamp (int): When message was received
            read_timestamp (int): When message was read
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
        self.message_type = message_type,
        self.received_timestamp = timing.format_timestamp(received_timestamp, "%Y/%m/%d %H:%M")
        self.read_timestamp = timing.format_timestamp(read_timestamp, "%Y/%m/%d %H:%M")
        
        # Extra attributes
        self.reply = None
        self.quoted_data = None
        self.caption = None
        self.thumb = None  # Android specific
        self.sticker = False

    def to_json(self) -> Dict[str, Any]:
        """Convert message to JSON-serializable dict."""
        return {
            'from_me': self.from_me,
            'timestamp': self.timestamp,
            'time': self.time,
            'media': self.media,
            'key_id': self.key_id,
            'meta': self.meta,
            'data': self.data,
            'sender': self.sender,
            'safe': self.safe,
            'mime': self.mime,
            'reply': self.reply,
            'quoted_data': self.quoted_data,
            'caption': self.caption,
            'thumb': self.thumb,
            'sticker': self.sticker
        }