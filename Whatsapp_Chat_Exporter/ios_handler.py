#!/usr/bin/python3

import json
import os
import logging
import shutil
from glob import glob
from tqdm import tqdm
from pathlib import Path
from mimetypes import MimeTypes
from markupsafe import escape as htmle
from Whatsapp_Chat_Exporter.data_model import ChatStore, Message
from Whatsapp_Chat_Exporter.utility import APPLE_TIME, get_chat_condition, Device
from Whatsapp_Chat_Exporter.utility import bytes_to_readable, convert_time_unit, safe_name
from Whatsapp_Chat_Exporter.poll import decode_poll_from_receipt_blob
from Whatsapp_Chat_Exporter.media_timestamp import process_media_with_timestamp


def contacts(db, data):
    """Process WhatsApp contacts with name and status information."""
    c = db.cursor()
    c.execute("""SELECT count() FROM ZWAADDRESSBOOKCONTACT""")
    total_row_number = c.fetchone()[0]
    logging.info(f"Pre-processing contacts...({total_row_number})", extra={"clear": True})

    # Check if expected columns exist before querying,  
    # to handle different WhatsApp versions (mainly ZLID).
    c.execute("PRAGMA table_info(ZWAADDRESSBOOKCONTACT)")
    column_names = [info[1] for info in c.fetchall()] 
    all_cols = ["ZWHATSAPPID", "ZLID", "ZFULLNAME", "ZABOUTTEXT"]
    columns = [col for col in all_cols if col in column_names]

    c.execute(f"""SELECT {', '.join(columns)} FROM ZWAADDRESSBOOKCONTACT""")
    with tqdm(total=total_row_number, desc="Processing contacts", unit="contact", leave=False) as pbar:
        while (content := c.fetchone()) is not None:
            zwhatsapp_id = content["ZWHATSAPPID"]
            if zwhatsapp_id is None:
                pbar.update(1)
                continue
            if not zwhatsapp_id.endswith("@s.whatsapp.net"):
                zwhatsapp_id += "@s.whatsapp.net"

            current_chat = ChatStore(Device.IOS)
            if content["ZFULLNAME"]:
                current_chat.name = content["ZFULLNAME"]
            if content["ZABOUTTEXT"]:
                current_chat.status = content["ZABOUTTEXT"]
            # Index by WhatsApp ID, with LID as alias if available
            data.add_chat(
                zwhatsapp_id,
                current_chat,
                content["ZLID"] if "ZLID" in columns and content["ZLID"] else None
            )

            pbar.update(1)
        total_time = pbar.format_dict['elapsed']
    logging.info(f"Pre-processed {total_row_number} contacts in {convert_time_unit(total_time)}")


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
    with tqdm(total=total_row_number, desc="Processing contacts", unit="contact", leave=False) as pbar:
        while (content := c.fetchone()) is not None:
            contact_name = get_contact_name(content)
            contact_id = content["ZCONTACTJID"]

            # Add or update chat
            if contact_id not in data:
                current_chat = data.add_chat(contact_id, ChatStore(Device.IOS, contact_name, media_folder))
            else:
                current_chat = data.get_chat(contact_id)
                # Only overwrite name if we have a better one (not a phone number)
                # or if there's no existing name
                if current_chat.name is None or contact_name is not None:
                    is_phone = contact_name.replace("+", "").replace(" ", "").isdigit() if contact_name else True
                    if not is_phone or current_chat.name is None:
                        current_chat.name = contact_name
                current_chat.my_avatar = os.path.join(media_folder, "Media/Profile/Photo.jpg")

            # Process avatar images
            process_contact_avatars(current_chat, media_folder, contact_id)
            pbar.update(1)
        total_time = pbar.format_dict['elapsed']
    logging.info(f"Processed {total_row_number} contacts in {convert_time_unit(total_time)}")

    # Pre-load push names for JIDs not yet in data (especially @lid group members)
    c.execute("""SELECT ZJID, ZPUSHNAME FROM ZWAPROFILEPUSHNAME WHERE ZPUSHNAME IS NOT NULL""")
    while (row := c.fetchone()) is not None:
        jid = row["ZJID"]
        if jid not in data:
            push_chat = ChatStore(Device.IOS)
            push_chat.name = row["ZPUSHNAME"]
            data.add_chat(jid, push_chat)
        elif data.get_chat(jid).name is None:
            data.get_chat(jid).name = row["ZPUSHNAME"]

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
    logging.info(f"Processing messages...(0/{total_row_number})", extra={"clear": True})

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

    reply_query = """SELECT ZSTANZAID,
                        ZTEXT,
                        ZTITLE
                     FROM ZWAMESSAGE
                        LEFT JOIN ZWAMEDIAITEM
                            ON ZWAMESSAGE.Z_PK = ZWAMEDIAITEM.ZMESSAGE
                     WHERE ZTEXT IS NOT NULL
                        OR ZTITLE IS NOT NULL;"""
    cursor2.execute(reply_query)
    message_map = {row[0][:17]: row[1] or row[2] for row in cursor2.fetchall() if row[0]}

    # Process each message
    with tqdm(total=total_row_number, desc="Processing messages", unit="msg", leave=False) as pbar:
        while (content := c.fetchone()) is not None:
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
                timezone_offset=timezone_offset,
                message_type=content["ZMESSAGETYPE"],
                received_timestamp=APPLE_TIME + content["ZSENTDATE"] if content["ZSENTDATE"] else None,
                read_timestamp=None  # TODO: Add timestamp
            )

            # Process message data
            invalid = process_message_data(message, content, is_group_message, data, message_map, no_reply)

            # Add valid messages to chat
            if not invalid:
                current_chat.add_message(message_pk, message)

            pbar.update(1)
        total_time = pbar.format_dict['elapsed']
    logging.info(f"Processed {total_row_number} messages in {convert_time_unit(total_time)}")


def process_message_data(message, content, is_group_message, data, message_map, no_reply):
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
        return process_metadata_message(message, content, is_group_message, data)

    # Handle quoted replies
    metadata = content["ZMETADATA"]
    if metadata is not None and not no_reply and len(metadata) >= 2 and metadata[0] == 0x2A:
        # The byte after the 0x2A tag is the length of the quoted message ID,
        # which is not always 0x14, so read it instead of assuming it.
        quoted_msg_id_length = metadata[1]
        quoted = metadata[2:2 + quoted_msg_id_length]
        if len(quoted) == quoted_msg_id_length and quoted.isascii():
            message.reply = quoted.decode("ascii")[:17]
            message.quoted_data = message_map.get(message.reply)

    # Skip poll vote update messages (type 66)
    if content["ZMESSAGETYPE"] == 66:
        return True  # Invalid, skip

    # Handle poll messages (type 46) - will be enriched by polls() later
    if content["ZMESSAGETYPE"] == 46:
        message.data = "\U0001f4ca Poll"
        return False  # Valid, populated later by polls()

    # Handle stickers
    if content["ZMESSAGETYPE"] == 15:
        message.sticker = True

    # Process message text
    process_message_text(message, content)

    return False  # Message is valid


def _parse_group_action(ztext, data):
    if ztext.endswith("@lid") or ztext.endswith("@s.whatsapp.net"):
        # This is likely a group member change action
        # Not really sure actually
        name = None
        if ztext in data:
            name = data.get_chat(ztext).name
        if "@" in ztext:
            fallback = ztext.split('@')[0]
        else:
            fallback = None
        entity = name or fallback

        return f"{entity} join the group"

    elif ztext.startswith("{") and ztext.endswith("}"):
        try:
            metadata = json.loads(ztext)
        except json.JSONDecodeError:
            return ztext  # Not a JSON string, return as-is
        entity = metadata.get('author', 'Someone')
        if entity is not "Someone":
            name = None
            if entity in data:
                name = data.get_chat(entity).name
            if "@" in entity:
                fallback = entity.split('@')[0]
            else:
                fallback = None
            entity = name or fallback
        return f"{entity} changed the group name to {metadata.get('subject', 'Unknown')}."
    elif ztext == "admin_add":
        return f"The administrator has restricted participant additions to admins only."
    else:
        return "Unsupported WhatsApp internal message."


def process_metadata_message(message, content, is_group_message, data):
    """Process metadata messages (action_type 6)."""
    if is_group_message:
        # Group
        if content["ZTEXT"] is not None:
            message.data = _parse_group_action(content["ZTEXT"], data)
            message.meta = True
            return False
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


def media(db, data, media_folder, filter_date, filter_chat, filter_empty, separate_media=False, fix_dot_files=False,
          embed_exif=False, rename_media=False, timezone_offset=0):
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
    logging.info(f"Processing media...(0/{total_row_number})", extra={"clear": True})

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
    with tqdm(total=total_row_number, desc="Processing media", unit="media", leave=False) as pbar:
        while (content := c.fetchone()) is not None:
            process_media_item(content, data, media_folder, mime, separate_media, fix_dot_files,
                               embed_exif, rename_media, timezone_offset)
            pbar.update(1)
        total_time = pbar.format_dict['elapsed']
    logging.info(f"Processed {total_row_number} media in {convert_time_unit(total_time)}")


def process_media_item(content, data, media_folder, mime, separate_media, fix_dot_files=False,
                       embed_exif=False, rename_media=False, timezone_offset=0):
    """Process a single media item."""
    file_path = f"{media_folder}/Message/{content['ZMEDIALOCALPATH']}"
    current_chat = data.get_chat(content["ZCONTACTJID"])
    message = current_chat.get_message(content["ZMESSAGE"])
    message.media = True

    if current_chat.media_base == "":
        current_chat.media_base = media_folder + "/"

    if os.path.isfile(file_path):
        # Set MIME type
        if content["ZVCARDSTRING"] is None:
            guess = mime.guess_type(file_path)[0]
            message.mime = guess if guess is not None else "application/octet-stream"
        else:
            message.mime = content["ZVCARDSTRING"]
        
        if fix_dot_files and file_path.endswith("."):
            extension = mime.guess_extension(message.mime)
            if message.mime == "application/octet-stream" or not extension:
                new_file_path = file_path[:-1]
            else:
                extension = mime.guess_extension(message.mime)
                new_file_path = file_path[:-1] + extension
            os.rename(file_path, new_file_path)
            file_path = new_file_path

        # Handle separate media option
        if separate_media:
            chat_display_name = safe_name(
                current_chat.name or message.sender or content["ZCONTACTJID"].split('@')[0])
            current_filename = file_path.split("/")[-1]
            new_folder = os.path.join(media_folder, "separated", chat_display_name)
            Path(new_folder).mkdir(parents=True, exist_ok=True)
            new_path = os.path.join(new_folder, current_filename)
            # Use timestamp processing if enabled
            if embed_exif or rename_media:
                final_path = process_media_with_timestamp(
                    file_path, new_path, message.timestamp,
                    timezone_offset, embed_exif, rename_media
                )
            else:
                final_path = new_path
                shutil.copy2(file_path, final_path)
        elif embed_exif or rename_media:
            # Handle in-place processing when not separating
            final_path = process_media_with_timestamp(
                file_path, file_path, message.timestamp,
                timezone_offset, embed_exif, rename_media
            )
        else:
            final_path = file_path
        message.data = os.path.join(*Path(final_path).parts[1:])
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
    logging.info(f"Processing vCards...(0/{total_row_number})", extra={"clear": True})

    # Create vCards directory
    path = f'{media_folder}/Message/vCards'
    Path(path).mkdir(parents=True, exist_ok=True)

    # Process each vCard
    with tqdm(total=total_row_number, desc="Processing vCards", unit="vcard", leave=False) as pbar:
        for content in contents:
            process_vcard_item(content, path, data)
            pbar.update(1)
        total_time = pbar.format_dict['elapsed']
    logging.info(f"Processed {total_row_number} vCards in {convert_time_unit(total_time)}")


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

    with tqdm(total=total_row_number, desc="Processing calls", unit="call", leave=False) as pbar:
        while (content := c.fetchone()) is not None:
            process_call_record(content, chat, data, timezone_offset)
            pbar.update(1)
        total_time = pbar.format_dict['elapsed']

    # Add calls chat to data
    data.add_chat("000000000000000", chat)
    logging.info(f"Processed {total_row_number} calls in {convert_time_unit(total_time)}")


def process_call_record(content, chat, data, timezone_offset):
    """Process a single call record."""
    ts = APPLE_TIME + int(content["ZDATE"])
    call = Message(
        from_me=content["ZINCOMING"] == 0,
        timestamp=ts,
        time=ts,
        key_id=content["ZCALLIDSTRING"],
        timezone_offset=timezone_offset
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


def _resolve_voter_name(voter_jid, is_creator, message, data):
    """Resolve a voter JID to a display name.

    Args:
        voter_jid (str or None): The voter's JID (often LID format like '123@lid').
        is_creator (bool): Whether this voter is the poll creator.
        message (Message): The poll message object.
        data (ChatCollection): The chat data collection for name lookups.

    Returns:
        str: The resolved display name.
    """
    if voter_jid is None:
        if is_creator:
            # Field 6 in the protobuf is always the device owner's vote,
            # not the poll message sender's vote
            return "You"
        return "Unknown"

    # Try direct lookup in data
    if voter_jid in data:
        chat = data.get_chat(voter_jid)
        if chat is not None and chat.name:
            return chat.name

    # Try with @s.whatsapp.net suffix
    if "@" not in voter_jid:
        jid_with_suffix = f"{voter_jid}@s.whatsapp.net"
        if jid_with_suffix in data:
            chat = data.get_chat(jid_with_suffix)
            if chat is not None and chat.name:
                return chat.name

    # Fallback: strip domain part
    if "@" in voter_jid:
        return voter_jid.split("@")[0]
    return voter_jid


def polls(db, data, filter_date, filter_chat, filter_empty):
    """Process WhatsApp poll messages (type 46) from the database.

    Queries ZWAMESSAGEINFO.ZRECEIPTINFO for poll messages, decodes the
    protobuf blobs, and enriches the corresponding Message objects with
    structured poll data.

    Args:
        db: SQLite database connection.
        data (ChatCollection): The chat data collection.
        filter_date: Date filter SQL fragment or None.
        filter_chat: Tuple of (include_filter, exclude_filter).
        filter_empty: Whether to filter empty chats.
    """
    c = db.cursor()

    # Build filter conditions
    chat_filter_include = get_chat_condition(
        filter_chat[0], True, ["ZWACHATSESSION.ZCONTACTJID", "ZMEMBERJID"], "ZGROUPINFO", "ios")
    chat_filter_exclude = get_chat_condition(
        filter_chat[1], False, ["ZWACHATSESSION.ZCONTACTJID", "ZMEMBERJID"], "ZGROUPINFO", "ios")
    date_filter = f'AND ZWAMESSAGE.ZMESSAGEDATE {filter_date}' if filter_date is not None else ''

    # Count poll messages
    count_query = f"""
        SELECT count()
        FROM ZWAMESSAGE
            JOIN ZWAMESSAGEINFO ON ZWAMESSAGEINFO.ZMESSAGE = ZWAMESSAGE.Z_PK
            INNER JOIN ZWACHATSESSION
                ON ZWAMESSAGE.ZCHATSESSION = ZWACHATSESSION.Z_PK
            LEFT JOIN ZWAGROUPMEMBER
                ON ZWAMESSAGE.ZGROUPMEMBER = ZWAGROUPMEMBER.Z_PK
        WHERE ZWAMESSAGE.ZMESSAGETYPE = 46
            AND ZWAMESSAGEINFO.ZRECEIPTINFO IS NOT NULL
            {date_filter}
            {chat_filter_include}
            {chat_filter_exclude}
    """
    c.execute(count_query)
    total_row_number = c.fetchone()[0]

    if total_row_number == 0:
        return

    logging.info(f"Processing polls...(0/{total_row_number})", extra={"clear": True})

    # Fetch poll data
    poll_query = f"""
        SELECT ZWACHATSESSION.ZCONTACTJID,
            ZWAMESSAGE.Z_PK AS ZMESSAGE,
            ZWAMESSAGEINFO.ZRECEIPTINFO
        FROM ZWAMESSAGE
            JOIN ZWAMESSAGEINFO ON ZWAMESSAGEINFO.ZMESSAGE = ZWAMESSAGE.Z_PK
            INNER JOIN ZWACHATSESSION
                ON ZWAMESSAGE.ZCHATSESSION = ZWACHATSESSION.Z_PK
            LEFT JOIN ZWAGROUPMEMBER
                ON ZWAMESSAGE.ZGROUPMEMBER = ZWAGROUPMEMBER.Z_PK
        WHERE ZWAMESSAGE.ZMESSAGETYPE = 46
            AND ZWAMESSAGEINFO.ZRECEIPTINFO IS NOT NULL
            {date_filter}
            {chat_filter_include}
            {chat_filter_exclude}
        ORDER BY ZWAMESSAGE.ZMESSAGEDATE ASC
    """
    c.execute(poll_query)

    with tqdm(total=total_row_number, desc="Processing polls", unit="poll", leave=False) as pbar:
        while (content := c.fetchone()) is not None:
            contact_id = content["ZCONTACTJID"]
            message_pk = content["ZMESSAGE"]
            receipt_blob = content["ZRECEIPTINFO"]

            current_chat = data.get_chat(contact_id)
            if current_chat is None:
                pbar.update(1)
                continue

            message = current_chat.get_message(message_pk)
            if message is None:
                pbar.update(1)
                continue

            try:
                poll_data = decode_poll_from_receipt_blob(receipt_blob)
            except Exception as e:
                logging.warning(f"Failed to decode poll {message_pk}: {e}")
                pbar.update(1)
                continue

            if poll_data is None:
                pbar.update(1)
                continue

            # Build structured poll result with vote tallies
            options = poll_data['options']
            votes = poll_data['votes']

            # Tally votes per option
            option_votes = {i: [] for i in range(len(options))}
            seen_voters = set()
            for vote in votes:
                voter_name = _resolve_voter_name(
                    vote.get('voter_jid'), vote.get('is_creator', False), message, data)
                voter_key = vote.get('voter_jid') or ("__creator__" if vote.get('is_creator') else "__unknown__")
                if voter_key not in seen_voters:
                    seen_voters.add(voter_key)
                for idx in vote.get('selected_indices', []):
                    if 0 <= idx < len(options):
                        option_votes[idx].append(voter_name)

            # Find max vote count for percentage calculation
            max_votes = max((len(v) for v in option_votes.values()), default=0)

            # Build option list with tallies
            option_list = []
            for i, opt_text in enumerate(options):
                voters = option_votes.get(i, [])
                vote_count = len(voters)
                vote_pct = (vote_count / max_votes * 100) if max_votes > 0 else 0
                option_list.append({
                    'text': opt_text,
                    'vote_count': vote_count,
                    'vote_pct': vote_pct,
                    'voters': voters,
                })

            total_voters = len(seen_voters)

            # Set poll data on message
            message.poll = {
                'type': 'poll',
                'question': poll_data['question'],
                'options': option_list,
                'total_voters': total_voters,
            }
            message.data = f"\U0001f4ca {poll_data['question']}"

            pbar.update(1)
        total_time = pbar.format_dict['elapsed']
    logging.info(f"Processed {total_row_number} polls in {convert_time_unit(total_time)}")


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
