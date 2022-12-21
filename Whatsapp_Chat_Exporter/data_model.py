from datetime import datetime
from typing import Union


class ChatStore():
    def __init__(self, name=None):
        if name is not None and not isinstance(name, str):
            raise TypeError("Name must be a string or None")
        self.name = name
        self.messages = {}
    
    def add_message(self, id, message):
        if not isinstance(message, Message):
            raise TypeError("Chat must be a Chat object")
        self.messages[id] = message

    def delete_message(self, id):
        if id in self.messages:
            del self.messages[id]

class Message():
    def __init__(self, from_me: Union[bool,int], timestamp: int, time: str, key_id: int):
        self.from_me = bool(from_me)
        self.timestamp = timestamp / 1000 if timestamp > 9999999999 else timestamp
        self.time = datetime.fromtimestamp(time/1000).strftime("%H:%M")
        self.media = False
        self.key_id = key_id
        self.meta = False
        self.data = None
        self.sender = None
        # Extra
        self.reply = None
        self.quoted_data = None
        self.caption = None

