#!/usr/bin/python3

import os
from datetime import datetime, tzinfo, timedelta
from typing import Union, Optional


class Timing():
    def __init__(self, timezone_offset: Optional[int]):
        self.timezone_offset = timezone_offset

    def format_timestamp(self, timestamp, format):
        if timestamp:
            timestamp = timestamp / 1000 if timestamp > 9999999999 else timestamp
            return datetime.fromtimestamp(timestamp, TimeZone(self.timezone_offset)).strftime(format)
        else:
            return None


class TimeZone(tzinfo):
    def __init__(self, offset):
        self.offset = offset
    def utcoffset(self, dt):
       return timedelta(hours=self.offset)
    def dst(self, dt):
       return timedelta(0)


class ChatStore():
    def __init__(self, type, name=None, media=None):
        if name is not None and not isinstance(name, str):
            raise TypeError("Name must be a string or None")
        self.name = name
        self.messages = {}
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
    
    def add_message(self, id, message):
        if not isinstance(message, Message):
            raise TypeError("message must be a Message object")
        self.messages[id] = message

    def delete_message(self, id):
        if id in self.messages:
            del self.messages[id]

    def to_json(self):
        serialized_msgs = {id: msg.to_json() for id, msg in self.messages.items()}
        return {
            'name': self.name,
            'type': self.type,
            'my_avatar': self.my_avatar,
            'their_avatar': self.their_avatar,
            'their_avatar_thumb': self.their_avatar_thumb,
            'status': self.status,
            'messages': serialized_msgs
        }

    def get_last_message(self):
        return tuple(self.messages.values())[-1]

    def get_messages(self):
        return self.messages.values()


class Message():
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
            message_type: int = None
        ):
        self.from_me = bool(from_me)
        self.timestamp = timestamp / 1000 if timestamp > 9999999999 else timestamp
        timing = Timing(timezone_offset)
        if isinstance(time, int) or isinstance(time, float):
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
        # Extra
        self.reply = None
        self.quoted_data = None
        self.caption = None
        self.thumb = None # Android specific
        self.sticker = False
    
    def to_json(self):
        return {
            'from_me'     : self.from_me,
            'timestamp'   : self.timestamp,
            'time'        : self.time,
            'media'       : self.media,
            'key_id'      : self.key_id,
            'meta'        : self.meta,
            'data'        : self.data,
            'sender'      : self.sender,
            'safe'        : self.safe,
            'mime'        : self.mime,
            'reply'       : self.reply,
            'quoted_data' : self.quoted_data,
            'caption'     : self.caption,
            'thumb'       : self.thumb,
            'sticker'     : self.sticker
        }
