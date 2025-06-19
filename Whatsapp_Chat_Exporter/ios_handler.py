#!/usr/bin/python3

import os
import logging
import shutil
from glob import glob
from pathlib import Path
from mimetypes import MimeTypes
from markupsafe import escape as htmle
from Whatsapp_Chat_Exporter.data_model import ChatStore, Message
from Whatsapp_Chat_Exporter.utility import APPLE_TIME, CLEAR_LINE, CURRENT_TZ_OFFSET, get_chat_condition
from Whatsapp_Chat_Exporter.utility import bytes_to_readable, convert_time_unit, safe_name, Device


logger = logging.getLogger(__name__)


def contacts(db, data):
    """Process WhatsApp contacts with status information."""
    c = db.cursor()
    c.execute("""SELECT count() FROM ZWAADDRESSBOOKCONTACT WHERE ZABOUTTEXT IS NOT NULL""")
    total_row_number = c.fetchone()[0]
    logger.info(f"Pre-processing contacts...({total_row_number})\r")

    c.execute("""SELECT ZWHATSAPPID, ZABOUTTEXT FROM ZWAADDRESSBOOKCONTACT WHERE ZABOUTTEXT IS NOT NULL""")
    content = c.fetchone()
    while content is not None:
        zwhatsapp_id = content["ZWHATSAPPID"]
        if not zwhatsapp_id.endswith("@s.whatsapp.net"):
            zwhatsapp_id += "@s.whatsapp.net"

        current_chat = ChatStore(Device.IOS)
        current_chat.status = content["ZABOUTTEXT"]
        data.add_chat(zwhatsapp_id, current_chat)
        content = c.fetchone()
    logger.info(f"Pre-processed {total_row_number} contacts{CLEAR_LINE}")


def process_contact_avatars(current_chat, media_folder, contact_id):
    """Process and assign avatar images for a contact."""
    path = f'{media_folder}/Media/Profile/{contact_id.split("@")[0]}'
    avatars = glob(f"{path}*")

    if 0 < len(avatars) <= 1:
        current_chat.their_avatar = avatars[0]
    else:
        for avatar in avatars:
            if avatar.endswith(".thumb") and current_chat.their_avatar_thumb is None:
                current_chat.their_avatar_thumb = avatar
            elif avatar.endswith(".jpg") and current_chat.their_avatar is None:
                current_chat.their_avatar = avatar


def get_contact_name(content):
    """Determine the appropriate contact name based on push name and partner name."""
    is_phone = content["ZPARTNERNAME"].replace("+", "").replace(" ", "").isdigit()
    if content["ZPUSHNAME"] is None or (content["ZPUSHNAME"] and not is_phone):
        return content["ZPARTNERNAME"]
    else:
        return content["ZPUSHNAME"]


def messages(db, data, media_folder, timezone_offset, filter_date, filter_chat, filter_empty, no_reply):
    """Process WhatsApp messages and contacts from the database."""
    c = db.cursor()
    cursor2 = db.cursor()

    # Build the chat filter conditions
    chat_filter_include = get_chat_condition(
        filter_chat[0], True, ["ZWACHATSESSION.ZCONTACTJID", "ZMEMBERJID"], "ZGROUPINFO", "ios")
    chat_filter_exclude = get_chat_condition(
        filter_chat[1], False, ["ZWACHATSESSION.ZCONTACTJID", "ZMEMBERJID"], "ZGROUPINFO", "ios")
    date_filter = f'AND ZMESSAGEDATE {filter_date}' if filter_date is not None else ''

    # Process contacts first
    contact_query = f"""
        SELECT count() 
        FROM (SELECT DISTINCT ZCONTACTJID,
            ZPARTNERNAME,
            ZWAPROFILEPUSHNAME.ZPUSHNAME
        FROM ZWACHATSESSION
            INNER JOIN ZWAMESSAGE
                ON ZWAMESSAGE.ZCHATSESSION = ZWACHATSESSION.Z_PK
            LEFT JOIN ZWAPROFILEPUSHNAME
                ON ZWACHATSESSION.ZCONTACTJID = ZWAPROFILEPUSHNAME.ZJID
            LEFT JOIN ZWAGROUPMEMBER
                    ON ZWAMESSAGE.ZGROUPMEMBER = ZWAGROUPMEMBER.Z_PK
        WHERE 1=1
            {chat_filter_include}
            {chat_filter_exclude}
        GROUP BY ZCONTACTJID);
    """
    c.execute(contact_query)
    total_row_number = c.fetchone()[0]
    logger.info(f"Processing contacts...({total_row_number})\r")

    # Get distinct contacts
    contacts_query = f"""
        SELECT DISTINCT ZCONTACTJID,
            ZPARTNERNAME,
            ZWAPROFILEPUSHNAME.ZPUSHNAME
        FROM ZWACHATSESSION
            INNER JOIN ZWAMESSAGE
                ON ZWAMESSAGE.ZCHATSESSION = ZWACHATSESSION.Z_PK
            LEFT JOIN ZWAPROFILEPUSHNAME
                ON ZWACHATSESSION.ZCONTACTJID = ZWAPROFILEPUSHNAME.ZJID
            LEFT JOIN ZWAGROUPMEMBER
                    ON ZWAMESSAGE.ZGROUPMEMBER = ZWAGROUPMEMBER.Z_PK
        WHERE 1=1
            {chat_filter_include}
            {chat_filter_exclude}
        GROUP BY ZCONTACTJID;
    """
    c.execute(contacts_query)

    # Process each contact
    content = c.fetchone()
    while content is not None:
        contact_name = get_contact_name(content)
        contact_id = content["ZCONTACTJID"]

        # Add or update chat
        if contact_id not in data:
            current_chat = data.add_chat(contact_id, ChatStore(Device.IOS, contact_name, media_folder))
        else:
            current_chat = data.get_chat(contact_id)
            current_chat.name = contact_name
            current_chat.my_avatar = os.path.join(media_folder, "Media/Profile/Photo.jpg")

        # Process avatar images
        process_contact_avatars(current_chat, media_folder, contact_id)
        content = c.fetchone()

    logger.info(f"Processed {total_row_number} contacts{CLEAR_LINE}")

    # Get message count
    message_count_query = f"""
        SELECT count()
        FROM ZWAMESSAGE
            INNER JOIN ZWACHATSESSION
                ON ZWAMESSAGE.ZCHATSESSION = ZWACHATSESSION.Z_PK
            LEFT JOIN ZWAGROUPMEMBER
                ON ZWAMESSAGE.ZGROUPMEMBER = ZWAGROUPMEMBER.Z_PK
        WHERE 1=1
            {date_filter}
            {chat_filter_include}
            {chat_filter_exclude}
    """
    c.execute(message_count_query)
    total_row_number = c.fetchone()[0]
    logger.info(f"Processing messages...(0/{total_row_number})\r")

    # Fetch messages
    messages_query = f"""
        SELECT ZCONTACTJID,
            ZWAMESSAGE.Z_PK,
            ZISFROMME,
            ZMESSAGEDATE,
            ZTEXT,
            ZMESSAGETYPE,
            ZWAGROUPMEMBER.ZMEMBERJID,
            ZMETADATA,
            ZSTANZAID,
            ZGROUPINFO,
            ZSENTDATE
        FROM ZWAMESSAGE
            LEFT JOIN ZWAGROUPMEMBER
                ON ZWAMESSAGE.ZGROUPMEMBER = ZWAGROUPMEMBER.Z_PK
            LEFT JOIN ZWAMEDIAITEM
                ON ZWAMESSAGE.Z_PK = ZWAMEDIAITEM.ZMESSAGE
            INNER JOIN ZWACHATSESSION
                ON ZWAMESSAGE.ZCHATSESSION = ZWACHATSESSION.Z_PK
        WHERE 1=1   
            {date_filter}
            {chat_filter_include}
            {chat_filter_exclude}
        ORDER BY ZMESSAGEDATE ASC;
    """
    c.execute(messages_query)

    # Process each message
    i = 0
    content = c.fetchone()
    while content is not None:
        contact_id = content["ZCONTACTJID"]
        message_pk = content["Z_PK"]
        is_group_message = content["ZGROUPINFO"] is not None

        # Ensure chat exists
        if contact_id not in data:
            current_chat = data.add_chat(contact_id, ChatStore(Device.IOS))
            process_contact_avatars(current_chat, media_folder, contact_id)
        else:
            current_chat = data.get_chat(contact_id)

        # Create message object
        ts = APPLE_TIME + content["ZMESSAGEDATE"]
        message = Message(
            from_me=content["ZISFROMME"],
            timestamp=ts,
            time=ts,
            key_id=content["ZSTANZAID"][:17],
            timezone_offset=timezone_offset if timezone_offset else CURRENT_TZ_OFFSET,
            message_type=content["ZMESSAGETYPE"],
            received_timestamp=APPLE_TIME + content["ZSENTDATE"] if content["ZSENTDATE"] else None,
            read_timestamp=None  # TODO: Add timestamp
        )

        # Process message data
        invalid = process_message_data(message, content, is_group_message, data, cursor2, no_reply)

        # Add valid messages to chat
        if not invalid:
            current_chat.add_message(message_pk, message)

        # Update progress
        i += 1
        if i % 1000 == 0:
            logger.info(f"Processing messages...({i}/{total_row_number})\r")
        content = c.fetchone()
    logger.info(f"Processed {total_row_number} messages{CLEAR_LINE}")


def process_message_data(message, content, is_group_message, data, cursor2, no_reply):
    """Process and set message data from content row."""
    # Handle group sender info
    if is_group_message and content["ZISFROMME"] == 0:
        name = None
        if content["ZMEMBERJID"] is not None:
            if content["ZMEMBERJID"] in data:
                name = data.get_chat(content["ZMEMBERJID"]).name
            if "@" in content["ZMEMBERJID"]:
                fallback = content["ZMEMBERJID"].split('@')[0]
            else:
                fallback = None
        else:
            fallback = None
        message.sender = name or fallback
    else:
        message.sender = None

    # Handle metadata messages
    if content["ZMESSAGETYPE"] == 6:
        return process_metadata_message(message, content, is_group_message)

    # Handle quoted replies
    if content["ZMETADATA"] is not None and content["ZMETADATA"].startswith(b"\x2a\x14") and not no_reply:
        quoted = content["ZMETADATA"][2:19]
        message.reply = quoted.decode()
        cursor2.execute(f"""SELECT ZTEXT
                            FROM ZWAMESSAGE
                            WHERE ZSTANZAID LIKE '{message.reply}%'""")
        quoted_content = cursor2.fetchone()
        if quoted_content and "ZTEXT" in quoted_content:
            message.quoted_data = quoted_content["ZTEXT"]
        else:
            message.quoted_data = None

    # Handle stickers
    if content["ZMESSAGETYPE"] == 15:
        message.sticker = True

    # Process message text
    process_message_text(message, content)

    return False  # Message is valid


def process_metadata_message(message, content, is_group_message):
    """Process metadata messages (action_type 6)."""
    if is_group_message:
        # Group
        if content["ZTEXT"] is not None:
            # Changed name
            try:
                int(content["ZTEXT"])
            except ValueError:
                msg = f"The group name changed to {content['ZTEXT']}"
                message.data = msg
                message.meta = True
                return False  # Valid message
            else:
                return True  # Invalid message
        else:
            message.data = None
            return False
    else:
        message.data = None
        return False


def process_message_text(message, content):
    """Process and format message text content."""
    if content["ZISFROMME"] == 1:
        if content["ZMESSAGETYPE"] == 14:
            msg = "Message deleted"
            message.meta = True
        else:
            msg = content["ZTEXT"]
            if msg is not None:
                msg = msg.replace("\r\n", "<br>").replace("\n", "<br>")
    else:
        if content["ZMESSAGETYPE"] == 14:
            msg = "Message deleted"
            message.meta = True
        else:
            msg = content["ZTEXT"]
            if msg is not None:
                msg = msg.replace("\r\n", "<br>").replace("\n", "<br>")

    message.data = msg


def media(db, data, media_folder, filter_date, filter_chat, filter_empty, separate_media=False):
    """Process media files from WhatsApp messages."""
    c = db.cursor()

    # Build filter conditions
    chat_filter_include = get_chat_condition(
        filter_chat[0], True, ["ZWACHATSESSION.ZCONTACTJID", "ZMEMBERJID"], "ZGROUPINFO", "ios")
    chat_filter_exclude = get_chat_condition(
        filter_chat[1], False, ["ZWACHATSESSION.ZCONTACTJID", "ZMEMBERJID"], "ZGROUPINFO", "ios")
    date_filter = f'AND ZMESSAGEDATE {filter_date}' if filter_date is not None else ''

    # Get media count
    media_count_query = f"""
        SELECT count()
        FROM ZWAMEDIAITEM
            INNER JOIN ZWAMESSAGE
                ON ZWAMEDIAITEM.ZMESSAGE = ZWAMESSAGE.Z_PK
            INNER JOIN ZWACHATSESSION
                ON ZWAMESSAGE.ZCHATSESSION = ZWACHATSESSION.Z_PK
            LEFT JOIN ZWAGROUPMEMBER
                ON ZWAMESSAGE.ZGROUPMEMBER = ZWAGROUPMEMBER.Z_PK
        WHERE 1=1
            {date_filter}
            {chat_filter_include}
            {chat_filter_exclude}
    """
    c.execute(media_count_query)
    total_row_number = c.fetchone()[0]
    logger.info(f"Processing media...(0/{total_row_number})\r")

    # Fetch media items
    media_query = f"""
        SELECT ZCONTACTJID,
            ZMESSAGE,
            ZMEDIALOCALPATH,
            ZMEDIAURL,
            ZVCARDSTRING,
            ZMEDIAKEY,
            ZTITLE
        FROM ZWAMEDIAITEM
            INNER JOIN ZWAMESSAGE
                ON ZWAMEDIAITEM.ZMESSAGE = ZWAMESSAGE.Z_PK
            INNER JOIN ZWACHATSESSION
                ON ZWAMESSAGE.ZCHATSESSION = ZWACHATSESSION.Z_PK
            LEFT JOIN ZWAGROUPMEMBER
                ON ZWAMESSAGE.ZGROUPMEMBER = ZWAGROUPMEMBER.Z_PK
        WHERE ZMEDIALOCALPATH IS NOT NULL
            {date_filter}
            {chat_filter_include}
            {chat_filter_exclude}
        ORDER BY ZCONTACTJID ASC
    """
    c.execute(media_query)

    # Process each media item
    mime = MimeTypes()
    i = 0
    content = c.fetchone()
    while content is not None:
        process_media_item(content, data, media_folder, mime, separate_media)

        # Update progress
        i += 1
        if i % 100 == 0:
            logger.info(f"Processing media...({i}/{total_row_number})\r")
        content = c.fetchone()
    logger.info(f"Processed {total_row_number} media{CLEAR_LINE}")


def process_media_item(content, data, media_folder, mime, separate_media):
    """Process a single media item."""
    file_path = f"{media_folder}/Message/{content['ZMEDIALOCALPATH']}"
    current_chat = data.get_chat(content["ZCONTACTJID"])
    message = current_chat.get_message(content["ZMESSAGE"])
    message.media = True

    if current_chat.media_base == "":
        current_chat.media_base = media_folder + "/"

    if os.path.isfile(file_path):
        message.data = '/'.join(file_path.split("/")[1:])

        # Set MIME type
        if content["ZVCARDSTRING"] is None:
            guess = mime.guess_type(file_path)[0]
            message.mime = guess if guess is not None else "application/octet-stream"
        else:
            message.mime = content["ZVCARDSTRING"]

        # Handle separate media option
        if separate_media:
            chat_display_name = safe_name(
                current_chat.name or message.sender or content["ZCONTACTJID"].split('@')[0])
            current_filename = file_path.split("/")[-1]
            new_folder = os.path.join(media_folder, "separated", chat_display_name)
            Path(new_folder).mkdir(parents=True, exist_ok=True)
            new_path = os.path.join(new_folder, current_filename)
            shutil.copy2(file_path, new_path)
            message.data = '/'.join(new_path.split("\\")[1:])
    else:
        # Handle missing media
        message.data = "The media is missing"
        message.mime = "media"
        message.meta = True

    # Add caption if available
    if content["ZTITLE"] is not None:
        message.caption = content["ZTITLE"]


def vcard(db, data, media_folder, filter_date, filter_chat, filter_empty):
    """Process vCard contacts from WhatsApp messages."""
    c = db.cursor()

    # Build filter conditions
    chat_filter_include = get_chat_condition(
        filter_chat[0], True, ["ZCONTACTJID", "ZMEMBERJID"], "ZGROUPINFO", "ios")
    chat_filter_exclude = get_chat_condition(
        filter_chat[1], False, ["ZCONTACTJID", "ZMEMBERJID"], "ZGROUPINFO", "ios")
    date_filter = f'AND ZWAMESSAGE.ZMESSAGEDATE {filter_date}' if filter_date is not None else ''

    # Fetch vCard mentions
    vcard_query = f"""
        SELECT DISTINCT ZWAVCARDMENTION.ZMEDIAITEM,
            ZWAMEDIAITEM.ZMESSAGE,
            ZCONTACTJID,
            ZVCARDNAME,
            ZVCARDSTRING
        FROM ZWAVCARDMENTION
            INNER JOIN ZWAMEDIAITEM
                ON ZWAVCARDMENTION.ZMEDIAITEM = ZWAMEDIAITEM.Z_PK
            INNER JOIN ZWAMESSAGE
                ON ZWAMEDIAITEM.ZMESSAGE = ZWAMESSAGE.Z_PK
            INNER JOIN ZWACHATSESSION
                ON ZWAMESSAGE.ZCHATSESSION = ZWACHATSESSION.Z_PK
            LEFT JOIN ZWAGROUPMEMBER
                ON ZWAMESSAGE.ZGROUPMEMBER = ZWAGROUPMEMBER.Z_PK
        WHERE 1=1
            {date_filter}
            {chat_filter_include}
            {chat_filter_exclude}
    """
    c.execute(vcard_query)
    contents = c.fetchall()
    total_row_number = len(contents)
    logger.info(f"Processing vCards...(0/{total_row_number})\r")

    # Create vCards directory
    path = f'{media_folder}/Message/vCards'
    Path(path).mkdir(parents=True, exist_ok=True)

    # Process each vCard
    for index, content in enumerate(contents):
        process_vcard_item(content, path, data)
        logger.info(f"Processing vCards...({index + 1}/{total_row_number})\r")
    logger.info(f"Processed {total_row_number} vCards{CLEAR_LINE}")


def process_vcard_item(content, path, data):
    """Process a single vCard item."""
    file_paths = []
    vcard_names = content["ZVCARDNAME"].split("_$!<Name-Separator>!$_")
    vcard_strings = content["ZVCARDSTRING"].split("_$!<VCard-Separator>!$_")

    # If this is a list of contacts
    if len(vcard_names) > len(vcard_strings):
        vcard_names.pop(0)  # Dismiss the first element, which is the group name

    # Save each vCard file
    for name, vcard_string in zip(vcard_names, vcard_strings):
        file_name = "".join(x for x in name if x.isalnum())
        file_name = file_name.encode('utf-8')[:230].decode('utf-8', 'ignore')
        file_path = os.path.join(path, f"{file_name}.vcf")
        file_paths.append(file_path)

        if not os.path.isfile(file_path):
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(vcard_string)

    # Create vCard summary and update message
    vcard_summary = "This media include the following vCard file(s):<br>"
    vcard_summary += " | ".join([f'<a href="{htmle(fp)}">{htmle(name)}</a>' for name,
                                fp in zip(vcard_names, file_paths)])

    message = data.get_chat(content["ZCONTACTJID"]).get_message(content["ZMESSAGE"])
    message.data = vcard_summary
    message.mime = "text/x-vcard"
    message.media = True
    message.meta = True
    message.safe = True


def calls(db, data, timezone_offset, filter_chat):
    """Process WhatsApp call records."""
    c = db.cursor()

    # Build filter conditions
    chat_filter_include = get_chat_condition(
        filter_chat[0], True, ["ZGROUPCALLCREATORUSERJIDSTRING"], None, "ios")
    chat_filter_exclude = get_chat_condition(
        filter_chat[1], False, ["ZGROUPCALLCREATORUSERJIDSTRING"], None, "ios")

    # Get call count
    call_count_query = f"""
        SELECT count()
        FROM ZWACDCALLEVENT
        WHERE 1=1
            {chat_filter_include}
            {chat_filter_exclude}
    """
    c.execute(call_count_query)
    total_row_number = c.fetchone()[0]
    if total_row_number == 0:
        return

    logger.info(f"Processed {total_row_number} calls{CLEAR_LINE}\n")

    # Fetch call records
    calls_query = f"""
        SELECT ZCALLIDSTRING,
            ZGROUPCALLCREATORUSERJIDSTRING,
            ZGROUPJIDSTRING,
            ZDATE,
            ZOUTCOME,
            ZBYTESRECEIVED + ZBYTESSENT AS bytes_transferred,
            ZDURATION,
            ZVIDEO,
            ZMISSED,
            ZINCOMING
        FROM ZWACDCALLEVENT
            INNER JOIN ZWAAGGREGATECALLEVENT
                ON ZWACDCALLEVENT.Z1CALLEVENTS = ZWAAGGREGATECALLEVENT.Z_PK
        WHERE 1=1
            {chat_filter_include}
            {chat_filter_exclude}
    """
    c.execute(calls_query)

    # Create calls chat
    chat = ChatStore(Device.ANDROID, "WhatsApp Calls")

    # Process each call
    content = c.fetchone()
    while content is not None:
        process_call_record(content, chat, data, timezone_offset)
        content = c.fetchone()

    # Add calls chat to data
    data.add_chat("000000000000000", chat)


def process_call_record(content, chat, data, timezone_offset):
    """Process a single call record."""
    ts = APPLE_TIME + int(content["ZDATE"])
    call = Message(
        from_me=content["ZINCOMING"] == 0,
        timestamp=ts,
        time=ts,
        key_id=content["ZCALLIDSTRING"],
        timezone_offset=timezone_offset if timezone_offset else CURRENT_TZ_OFFSET
    )

    # Set sender info
    _jid = content["ZGROUPCALLCREATORUSERJIDSTRING"]
    name = data.get_chat(_jid).name if _jid in data else None
    if _jid is not None and "@" in _jid:
        fallback = _jid.split('@')[0]
    else:
        fallback = None
    call.sender = name or fallback

    # Set call metadata
    call.meta = True
    call.data = format_call_data(call, content)

    # Add call to chat
    chat.add_message(call.key_id, call)


def format_call_data(call, content):
    """Format call data message based on call attributes."""
    # Basic call info
    call_data = (
        f"A {'group ' if content['ZGROUPJIDSTRING'] is not None else ''}"
        f"{'video' if content['ZVIDEO'] == 1 else 'voice'} "
        f"call {'to' if call.from_me else 'from'} "
        f"{call.sender} was "
    )

    # Call outcome
    if content['ZOUTCOME'] in (1, 4):
        call_data += "not answered." if call.from_me else "missed."
    elif content['ZOUTCOME'] == 2:
        call_data += "failed."
    elif content['ZOUTCOME'] == 0:
        call_time = convert_time_unit(int(content['ZDURATION']))
        call_bytes = bytes_to_readable(content['bytes_transferred'])
        call_data += (
            f"initiated and lasted for {call_time} "
            f"with {call_bytes} data transferred."
        )
    else:
        call_data += "in an unknown state."

    return call_data
