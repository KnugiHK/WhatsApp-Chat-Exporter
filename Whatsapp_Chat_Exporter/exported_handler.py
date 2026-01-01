#!/usr/bin/python3

import os
import logging
from datetime import datetime
from mimetypes import MimeTypes
from Whatsapp_Chat_Exporter.data_model import ChatStore, Message
from Whatsapp_Chat_Exporter.utility import CLEAR_LINE, Device


logger = logging.getLogger(__name__)


def messages(path, data, assume_first_as_me=False):
    """
    Extracts messages from an exported WhatsApp chat file.

    Args:
        path: Path to the exported chat file
        data: Data container object to store the parsed chat
        assume_first_as_me: If True, assumes the first message is sent from the user without asking

    Returns:
        Updated data container with extracted messages
    """
    # Create a new chat in the data container
    chat = data.add_chat("ExportedChat", ChatStore(Device.EXPORTED))
    you = ""  # Will store the username of the current user
    user_identification_done = False  # Flag to track if user identification has been done

    # First pass: count total lines for progress reporting
    with open(path, "r", encoding="utf8") as file:
        total_row_number = sum(1 for _ in file)

    # Second pass: process the messages
    with open(path, "r", encoding="utf8") as file:
        for index, line in enumerate(file):
            you, user_identification_done = process_line(
                line, index, chat, path, you,
                assume_first_as_me, user_identification_done
            )

            # Show progress
            if index % 1000 == 0:
                logger.info(f"Processing messages & media...({index}/{total_row_number})\r")

    logger.info(f"Processed {total_row_number} messages & media{CLEAR_LINE}")
    return data


def process_line(line, index, chat, file_path, you, assume_first_as_me, user_identification_done):
    """
    Process a single line from the chat file

    Returns:
        Tuple of (updated_you_value, updated_user_identification_done_flag)
    """
    parts = line.split(" - ", 1)

    # Check if this is a new message (has timestamp format)
    if len(parts) > 1:
        time = parts[0]
        you, user_identification_done = process_new_message(
            time, parts[1], index, chat, you, file_path,
            assume_first_as_me, user_identification_done
        )
    else:
        # This is a continuation of the previous message
        process_message_continuation(line, index, chat)

    return you, user_identification_done


def process_new_message(time, content, index, chat, you, file_path,
                        assume_first_as_me, user_identification_done):
    """
    Process a line that contains a new message

    Returns:
        Tuple of (updated_you_value, updated_user_identification_done_flag)
    """
    # Create a new message
    msg = Message(
        from_me=False,  # Will be updated later if needed
        timestamp=datetime.strptime(time, "%d/%m/%Y, %H:%M").timestamp(),
        time=time.split(", ")[1].strip(),
        key_id=index,
        received_timestamp=None,
        read_timestamp=None
    )

    # Check if this is a system message (no name:message format)
    if ":" not in content:
        msg.data = content
        msg.meta = True
    else:
        # Process user message
        name, message = content.strip().split(":", 1)

        # Handle user identification
        if you == "":
            if chat.name is None:
                # First sender identification
                if not user_identification_done:
                    if not assume_first_as_me:
                        # Ask only once if this is the user
                        you = prompt_for_user_identification(name)
                        user_identification_done = True
                    else:
                        you = name
                        user_identification_done = True
            else:
                # If we know the chat name, anyone else must be "you"
                if name != chat.name:
                    you = name

        # Set the chat name if needed
        if chat.name is None and name != you:
            chat.name = name

        # Determine if this message is from the current user
        msg.from_me = (name == you)

        # Process message content
        process_message_content(msg, message, file_path)

    chat.add_message(index, msg)
    return you, user_identification_done


def process_message_content(msg, message, file_path):
    """Process and set the content of a message based on its type"""
    if "<Media omitted>" in message:
        msg.data = "The media is omitted in the chat"
        msg.mime = "media"
        msg.meta = True
    elif "(file attached)" in message:
        process_attached_file(msg, message, file_path)
    else:
        msg.data = message.replace("\r\n", "<br>").replace("\n", "<br>")


def process_attached_file(msg, message, file_path):
    """Process an attached file in a message"""
    mime = MimeTypes()
    msg.media = True

    # Extract file path and check if it exists
    file_name = message.split("(file attached)")[0].strip()
    attached_file_path = os.path.join(os.path.dirname(file_path), file_name)

    if os.path.isfile(attached_file_path):
        msg.data = attached_file_path
        guess = mime.guess_type(attached_file_path)[0]
        msg.mime = guess if guess is not None else "application/octet-stream"
    else:
        msg.data = "The media is missing"
        msg.mime = "media"
        msg.meta = True


def process_message_continuation(line, index, chat):
    """Process a line that continues a previous message"""
    # Find the previous message
    lookback = index - 1
    while lookback not in chat.keys():
        lookback -= 1

    msg = chat.get_message(lookback)

    # Add the continuation line to the message
    if msg.media:
        msg.caption = line.strip()
    else:
        msg.data += "<br>" + line.strip()


def prompt_for_user_identification(name):
    """Ask the user if the given name is their username"""
    while True:
        ans = input(f"Is '{name}' you? (Y/N)").lower()
        if ans == "y":
            return name
        elif ans == "n":
            return ""
