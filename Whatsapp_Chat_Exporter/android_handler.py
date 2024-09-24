#!/usr/bin/python3

import sqlite3
import os
import io
import hmac
import shutil
from pathlib import Path
from mimetypes import MimeTypes
from markupsafe import escape as htmle
from hashlib import sha256
from base64 import b64decode, b64encode
from datetime import datetime
from Whatsapp_Chat_Exporter.data_model import ChatStore, Message
from Whatsapp_Chat_Exporter.utility import MAX_SIZE, ROW_SIZE, DbType, convert_time_unit, determine_metadata
from Whatsapp_Chat_Exporter.utility import rendering, Crypt, Device, get_file_name, setup_template, JidType
from Whatsapp_Chat_Exporter.utility import brute_force_offset, CRYPT14_OFFSETS, get_status_location
from Whatsapp_Chat_Exporter.utility import get_chat_condition, slugify, bytes_to_readable, chat_is_empty

try:
    import zlib
    from Crypto.Cipher import AES
except ModuleNotFoundError:
    support_backup = False
else:
    support_backup = True
try:
    import javaobj
except ModuleNotFoundError:
    support_crypt15 = False
else:
    support_crypt15 = True


def _generate_hmac_of_hmac(key_stream):
    key = hmac.new(
        hmac.new(
            b'\x00' * 32,
            key_stream,
            sha256
        ).digest(),
        b"backup encryption\x01",
        sha256
    )
    return key.digest(), key_stream


def _extract_encrypted_key(keyfile):
    key_stream = b""
    for byte in javaobj.loads(keyfile):
        key_stream += byte.to_bytes(1, "big", signed=True)

    return _generate_hmac_of_hmac(key_stream)


def decrypt_backup(database, key, output, crypt=Crypt.CRYPT14, show_crypt15=False, db_type=DbType.MESSAGE):
    if not support_backup:
        return 1
    if isinstance(key, io.IOBase):
        key = key.read()
        if crypt is not Crypt.CRYPT15:
            t1 = key[30:62]
    if crypt is not Crypt.CRYPT15 and len(key) != 158:
        raise ValueError("The key file must be 158 bytes")
    # Determine the IV and database offsets
    if crypt == Crypt.CRYPT14:
        if len(database) < 191:
            raise ValueError("The crypt14 file must be at least 191 bytes")
        current_try = 0
        offsets = CRYPT14_OFFSETS[current_try]
        t2 = database[15:47]
        iv = database[offsets["iv"]:offsets["iv"] + 16]
        db_ciphertext = database[offsets["db"]:]
    elif crypt == Crypt.CRYPT12:
        if len(database) < 67:
            raise ValueError("The crypt12 file must be at least 67 bytes")
        t2 = database[3:35]
        iv = database[51:67]
        db_ciphertext = database[67:-20]
    elif crypt == Crypt.CRYPT15:
        if not support_crypt15:
            return 1
        if len(database) < 131:
            raise ValueError("The crypt15 file must be at least 131 bytes")
        t1 = t2 = None
        if db_type == DbType.MESSAGE:
            iv = database[8:24]
            db_offset = database[0] + 2  # Skip protobuf + protobuf size and backup type
        elif db_type == DbType.CONTACT:
            iv = database[7:23]
            db_offset = database[0] + 1  # Skip protobuf + protobuf size
        db_ciphertext = database[db_offset:]

    if t1 != t2:
        raise ValueError("The signature of key file and backup file mismatch")

    if crypt == Crypt.CRYPT15:
        if len(key) == 32:
            main_key, hex_key = _generate_hmac_of_hmac(key)
        else:
            main_key, hex_key = _extract_encrypted_key(key)
        if show_crypt15:
            hex_key = [hex_key.hex()[c:c+4] for c in range(0, len(hex_key.hex()), 4)]
            print("The HEX key of the crypt15 backup is: " + ' '.join(hex_key))
    else:
        main_key = key[126:]
    decompressed = False
    while not decompressed:
        cipher = AES.new(main_key, AES.MODE_GCM, iv)
        db_compressed = cipher.decrypt(db_ciphertext)
        try:
            db = zlib.decompress(db_compressed)
        except zlib.error:
            if crypt == Crypt.CRYPT14:
                current_try += 1
                if current_try < len(CRYPT14_OFFSETS):
                    offsets = CRYPT14_OFFSETS[current_try]
                    iv = database[offsets["iv"]:offsets["iv"] + 16]
                    db_ciphertext = database[offsets["db"]:]
                    continue
                else:
                    print("Common offsets are not applicable to "
                          "your backup. Trying to brute force it...")
                    for start_iv, end_iv, start_db in brute_force_offset():
                        iv = database[start_iv:end_iv]
                        db_ciphertext = database[start_db:]
                        cipher = AES.new(main_key, AES.MODE_GCM, iv)
                        db_compressed = cipher.decrypt(db_ciphertext)
                        try:
                            db = zlib.decompress(db_compressed)
                        except zlib.error:
                            continue
                        else:
                            decompressed = True
                            print(
                                f"The offsets of your IV and database are {start_iv} and "
                                f"{start_db}, respectively. To include your offsets in the "
                                "program, please report it by creating an issue on GitHub: "
                                "https://github.com/KnugiHK/Whatsapp-Chat-Exporter/discussions/47"
                            )
                            break
                    if not decompressed:
                        return 2
            else:
                return 3
        else:
            decompressed = True
        if db[0:6].upper() == b"SQLITE":
            with open(output, "wb") as f:
                f.write(db)
            return 0
        else:
            raise ValueError("The plaintext is not a SQLite database. Did you use the key to encrypt something...")


def contacts(db, data):
    # Get contacts
    c = db.cursor()
    c.execute("""SELECT count() FROM wa_contacts""")
    total_row_number = c.fetchone()[0]
    if total_row_number == 0:
        print("No contacts profiles found in the default database, consider using --enrich-from-vcards for adopting names from exported contacts from Google")
        return False
    else:
        print(f"Processing contacts...({total_row_number})")

    c.execute("""SELECT jid, COALESCE(display_name, wa_name) as display_name, status FROM wa_contacts; """)
    row = c.fetchone()
    while row is not None:
        data[row["jid"]] = ChatStore(Device.ANDROID, row["display_name"])
        if row["status"] is not None:
            data[row["jid"]].status = row["status"]
        row = c.fetchone()


def messages(db, data, media_folder, timezone_offset, filter_date, filter_chat):
    # Get message history
    c = db.cursor()
    try:
        c.execute(f"""SELECT count()
                      FROM messages
                        INNER JOIN jid
                            ON messages.key_remote_jid = jid.raw_string
                      WHERE 1=1
                        {f'AND timestamp {filter_date}' if filter_date is not None else ''}
                        {get_chat_condition(filter_chat[0], True, ["messages.key_remote_jid", "messages.remote_resource"], "jid", "android")}
                        {get_chat_condition(filter_chat[1], False, ["messages.key_remote_jid", "messages.remote_resource"], "jid", "android")}""")

    except sqlite3.OperationalError:
        c.execute(f"""SELECT count()
                      FROM message
                        LEFT JOIN chat
                            ON chat._id = message.chat_row_id
                        INNER JOIN jid
                            ON jid._id = chat.jid_row_id
                        LEFT JOIN jid jid_group
                            ON jid_group._id = message.sender_jid_row_id
                      WHERE 1=1
                        {f'AND timestamp {filter_date}' if filter_date is not None else ''}
                        {get_chat_condition(filter_chat[0], True, ["jid.raw_string", "jid_group.raw_string"], "jid", "android")}
                        {get_chat_condition(filter_chat[1], False, ["jid.raw_string", "jid_group.raw_string"], "jid", "android")}""")
    total_row_number = c.fetchone()[0]
    print(f"Processing messages...(0/{total_row_number})", end="\r")

    try:
        c.execute(f"""SELECT messages.key_remote_jid,
                            messages._id,
                            messages.key_from_me,
                            messages.timestamp,
                            messages.data,
                            messages.status,
                            messages.edit_version,
                            messages.thumb_image,
                            messages.remote_resource,
                            CAST(messages.media_wa_type as INTEGER) as media_wa_type,
                            messages.latitude,
                            messages.longitude,
                            messages_quotes.key_id as quoted,
                            messages.key_id,
                            messages_quotes.data as quoted_data,
                            messages.media_caption,
                            missed_call_logs.video_call,
                            chat.subject as chat_subject,
                            message_system.action_type,
                            message_system_group.is_me_joined,
                            jid_old.raw_string as old_jid,
                            jid_new.raw_string as new_jid,
                            jid_global.type as jid_type,
                            group_concat(receipt_user.receipt_timestamp) as receipt_timestamp,
                            group_concat(messages.received_timestamp) as received_timestamp,
                            group_concat(receipt_user.read_timestamp) as read_timestamp,
                            group_concat(receipt_user.played_timestamp) as played_timestamp,
                            group_concat(messages.read_device_timestamp) as read_device_timestamp
                    FROM messages
                        LEFT JOIN messages_quotes
                            ON messages.quoted_row_id = messages_quotes._id
						LEFT JOIN missed_call_logs
							ON messages._id = missed_call_logs.message_row_id
                        INNER JOIN jid jid_global
                            ON messages.key_remote_jid = jid_global.raw_string
                        LEFT JOIN chat
                            ON chat.jid_row_id = jid_global._id
                        LEFT JOIN message_system
                            ON message_system.message_row_id = messages._id
                        LEFT JOIN message_system_group
                            ON message_system_group.message_row_id = messages._id
                        LEFT JOIN message_system_number_change
                            ON message_system_number_change.message_row_id = messages._id
                        LEFT JOIN jid jid_old
                            ON jid_old._id = message_system_number_change.old_jid_row_id
                        LEFT JOIN jid jid_new
                            ON jid_new._id = message_system_number_change.new_jid_row_id
                        LEFT JOIN receipt_user
                            ON receipt_user.message_row_id = messages._id
                    WHERE messages.key_remote_jid <> '-1'
                        {f'AND messages.timestamp {filter_date}' if filter_date is not None else ''}
                        {get_chat_condition(filter_chat[0], True, ["messages.key_remote_jid", "messages.remote_resource"], "jid_global", "android")}
                        {get_chat_condition(filter_chat[1], False, ["messages.key_remote_jid", "messages.remote_resource"], "jid_global", "android")}
                    GROUP BY messages._id
                    ORDER BY messages.timestamp ASC;"""
        )
    except sqlite3.OperationalError:
        try:
            c.execute(f"""SELECT jid_global.raw_string as key_remote_jid,
                            message._id,
                            message.from_me as key_from_me,
                            message.timestamp,
                            message.text_data as data,
                            message.status,
                            message_future.version as edit_version,
                            message_thumbnail.thumbnail as thumb_image,
                            message_media.file_path as remote_resource,
                            message_location.latitude,
                            message_location.longitude,
                            message_quoted.key_id as quoted,
                            message.key_id,
                            message_quoted.text_data as quoted_data,
                            message.message_type as media_wa_type,
                            jid_group.raw_string as group_sender_jid,
                            chat.subject as chat_subject,
							missed_call_logs.video_call,
                            message.sender_jid_row_id,
                            message_system.action_type,
                            message_system_group.is_me_joined,
                            jid_old.raw_string as old_jid,
                            jid_new.raw_string as new_jid,
                            jid_global.type as jid_type,
                            group_concat(receipt_user.receipt_timestamp) as receipt_timestamp,
                            group_concat(message.received_timestamp) as received_timestamp,
                            group_concat(receipt_user.read_timestamp) as read_timestamp,
                            group_concat(receipt_user.played_timestamp) as played_timestamp
                    FROM message
                        LEFT JOIN message_quoted
                            ON message_quoted.message_row_id = message._id
                        LEFT JOIN message_location
                            ON message_location.message_row_id = message._id
                        LEFT JOIN message_media
                            ON message_media.message_row_id = message._id
                        LEFT JOIN message_thumbnail
                            ON message_thumbnail.message_row_id = message._id
                        LEFT JOIN message_future
                            ON message_future.message_row_id = message._id
                        LEFT JOIN chat
                            ON chat._id = message.chat_row_id
                        INNER JOIN jid jid_global
                            ON jid_global._id = chat.jid_row_id
                        LEFT JOIN jid jid_group
                            ON jid_group._id = message.sender_jid_row_id
						LEFT JOIN missed_call_logs
							ON message._id = missed_call_logs.message_row_id
                        LEFT JOIN message_system
                            ON message_system.message_row_id = message._id
                        LEFT JOIN message_system_group
                            ON message_system_group.message_row_id = message._id
                        LEFT JOIN message_system_number_change
                            ON message_system_number_change.message_row_id = message._id
                        LEFT JOIN jid jid_old
                            ON jid_old._id = message_system_number_change.old_jid_row_id
                        LEFT JOIN jid jid_new
                            ON jid_new._id = message_system_number_change.new_jid_row_id
                        LEFT JOIN receipt_user
                            ON receipt_user.message_row_id = message._id
                    WHERE key_remote_jid <> '-1'
                        {f'AND message.timestamp {filter_date}' if filter_date is not None else ''}
                        {get_chat_condition(filter_chat[0], True, ["key_remote_jid", "jid_group.raw_string"], "jid_global", "android")}
                        {get_chat_condition(filter_chat[1], False, ["key_remote_jid", "jid_group.raw_string"], "jid_global", "android")}
                    GROUP BY message._id;"""
            )
        except Exception as e:
            raise e
        else:
            table_message = True
    else:
        table_message = False
    i = 0
    while True:
        try:
            content = c.fetchone()
        except sqlite3.OperationalError:
            continue
        else:
            break
    while content is not None:
        if content["key_remote_jid"] not in data:
            data[content["key_remote_jid"]] = ChatStore(Device.ANDROID, content["chat_subject"])
        if content["key_remote_jid"] is None:
            continue  # Not sure
        if "sender_jid_row_id" in content:
            sender_jid_row_id = content["sender_jid_row_id"]
        else:
            sender_jid_row_id = None
        message = Message(
            from_me=not sender_jid_row_id and content["key_from_me"],
            timestamp=content["timestamp"],
            time=content["timestamp"],
            key_id=content["key_id"],
            timezone_offset=timezone_offset
        )
        if isinstance(content["data"], bytes):
            message.data = ("The message is binary data and its base64 is "
                '<a href="https://gchq.github.io/CyberChef/#recipe=From_Base64'
                "('A-Za-z0-9%2B/%3D',true,false)Text_Encoding_Brute_Force"
                f"""('Decode')&input={b64encode(b64encode(content["data"])).decode()}">""")
            message.data += b64encode(content["data"]).decode("utf-8") + "</a>"
            message.safe = message.meta = True
            data[content["key_remote_jid"]].add_message(content["_id"], message)
            i += 1
            content = c.fetchone()
            continue
        if content["jid_type"] == JidType.GROUP and content["key_from_me"] == 0:
            name = fallback = None
            if table_message:
                if content["sender_jid_row_id"] > 0:
                    _jid = content["group_sender_jid"]
                    if _jid in data:
                        name = data[_jid].name
                    if "@" in _jid:
                        fallback = _jid.split('@')[0]
            else:
                if content["remote_resource"] is not None:
                    if content["remote_resource"] in data:
                        name = data[content["remote_resource"]].name
                    if "@" in content["remote_resource"]:
                        fallback = content["remote_resource"].split('@')[0]

            message.sender = name or fallback
        else:
            message.sender = None

        if content["quoted"] is not None:
            message.reply = content["quoted"]
            if content["quoted_data"] is not None and len(content["quoted_data"]) > 200:
                message.quoted_data = content["quoted_data"][:201] + "..."
            else:
                message.quoted_data = content["quoted_data"]
        else:
            message.reply = None

        if not table_message and content["media_caption"] is not None:
            # Old schema
            message.caption = content["media_caption"]
        elif table_message and content["media_wa_type"] == 1 and content["data"] is not None:
            # New schema
            message.caption = content["data"]
        else:
            message.caption = None

        if content["status"] == 6:  # 6 = Metadata, otherwise assume a message
            message.meta = True
            name = fallback = None
            if table_message:
                if content["sender_jid_row_id"] > 0:
                    _jid = content["group_sender_jid"]
                    if _jid in data:
                        name = data[_jid].name
                    if "@" in _jid:
                        fallback = _jid.split('@')[0]
                else:
                    name = "You"
            else:
                _jid = content["remote_resource"]
                if _jid is not None:
                    if _jid in data:
                        name = data[_jid].name
                    if "@" in _jid:
                        fallback = _jid.split('@')[0]
                else:
                    name = "You"
            message.data = determine_metadata(content, name or fallback)
            if isinstance(message.data, str) and "<br>" in message.data:
                message.safe = True
            if message.data is None:
                if content["video_call"] is not None:  # Missed call
                    message.meta = True
                    if content["video_call"] == 1:
                        message.data = "A video call was missed"
                    elif content["video_call"] == 0:
                        message.data = "A voice call was missed"
                elif content["data"] is None and content["thumb_image"] is None:
                    message.meta = True
                    message.data = None
        else:
            # Real message
            message.sticker = content["media_wa_type"] == 20  # Sticker is a message
            if content["key_from_me"] == 1:
                if content["status"] == 5 and content["edit_version"] == 7 or table_message and content["media_wa_type"] == 15:
                    msg = "Message deleted"
                    message.meta = True
                else:
                    if content["media_wa_type"] == 5:
                        msg = f"Location shared: {content['latitude'], content['longitude']}"
                        message.meta = True
                    else:
                        msg = content["data"]
                        if msg is not None:
                            if "\r\n" in msg:
                                msg = msg.replace("\r\n", " <br>")
                            if "\n" in msg:
                                msg = msg.replace("\n", " <br>")
            else:
                if content["status"] == 0 and content["edit_version"] == 7 or table_message and content["media_wa_type"] == 15:
                    msg = "Message deleted"
                    message.meta = True
                else:
                    if content["media_wa_type"] == 5:
                        msg = f"Location shared: {content['latitude'], content['longitude']}"
                        message.meta = True
                    else:
                        msg = content["data"]
                        if msg is not None:
                            if "\r\n" in msg:
                                msg = msg.replace("\r\n", " <br>")
                            if "\n" in msg:
                                msg = msg.replace("\n", " <br>")
            message.data = msg

        data[content["key_remote_jid"]].add_message(content["_id"], message)
        i += 1
        if i % 1000 == 0:
            print(f"Processing messages...({i}/{total_row_number})", end="\r")
        while True:
            try:
                content = c.fetchone()
            except sqlite3.OperationalError:
                continue
            else:
                break
    print(f"Processing messages...({total_row_number}/{total_row_number})", end="\r")


def media(db, data, media_folder, filter_date, filter_chat, separate_media=True):
    # Get media
    c = db.cursor()
    try:
        c.execute(f"""SELECT count()
                    FROM message_media
                        INNER JOIN messages
                            ON message_media.message_row_id = messages._id
                        INNER JOIN jid
                            ON messages.key_remote_jid = jid.raw_string
                    WHERE 1=1  
                        {f'AND messages.timestamp {filter_date}' if filter_date is not None else ''}
                        {get_chat_condition(filter_chat[0], True, ["messages.key_remote_jid", "remote_resource"], "jid", "android")}
                        {get_chat_condition(filter_chat[1], False, ["messages.key_remote_jid", "remote_resource"], "jid", "android")}""")
    except sqlite3.OperationalError:
        c.execute(f"""SELECT count()
                    FROM message_media
                        INNER JOIN message
                            ON message_media.message_row_id = message._id
                        LEFT JOIN chat
                            ON chat._id = message.chat_row_id
                        INNER JOIN jid
                            ON jid._id = chat.jid_row_id
                        LEFT JOIN jid jid_group
                            ON jid_group._id = message.sender_jid_row_id
                    WHERE 1=1    
                        {f'AND message.timestamp {filter_date}' if filter_date is not None else ''}
                        {get_chat_condition(filter_chat[0], True, ["jid.raw_string", "jid_group.raw_string"], "jid", "android")}
                        {get_chat_condition(filter_chat[1], False, ["jid.raw_string", "jid_group.raw_string"], "jid", "android")}""")
    total_row_number = c.fetchone()[0]
    print(f"\nProcessing media...(0/{total_row_number})", end="\r")
    i = 0
    try:
        c.execute(f"""SELECT messages.key_remote_jid,
                        message_row_id,
                        file_path,
                        message_url,
                        mime_type,
                        media_key,
                        file_hash,
						thumbnail
                 FROM message_media
                    INNER JOIN messages
                        ON message_media.message_row_id = messages._id
					LEFT JOIN media_hash_thumbnail
						ON message_media.file_hash = media_hash_thumbnail.media_hash
                    INNER JOIN jid
                        ON messages.key_remote_jid = jid.raw_string
                WHERE jid.type <> 7
                    {f'AND messages.timestamp {filter_date}' if filter_date is not None else ''}
                    {get_chat_condition(filter_chat[0], True, ["messages.key_remote_jid", "remote_resource"], "jid", "android")}
                    {get_chat_condition(filter_chat[1], False, ["messages.key_remote_jid", "remote_resource"], "jid", "android")}
                ORDER BY messages.key_remote_jid ASC"""
        )
    except sqlite3.OperationalError:
        c.execute(f"""SELECT jid.raw_string as key_remote_jid,
                    message_row_id,
                    file_path,
                    message_url,
                    mime_type,
                    media_key,
                    file_hash,
                    thumbnail
                FROM message_media
                    INNER JOIN message
                        ON message_media.message_row_id = message._id
                    LEFT JOIN chat
                        ON chat._id = message.chat_row_id
                    INNER JOIN jid
                        ON jid._id = chat.jid_row_id
                    LEFT JOIN media_hash_thumbnail
						ON message_media.file_hash = media_hash_thumbnail.media_hash
                    LEFT JOIN jid jid_group
                        ON jid_group._id = message.sender_jid_row_id
                WHERE jid.type <> 7
                    {f'AND message.timestamp {filter_date}' if filter_date is not None else ''}
                    {get_chat_condition(filter_chat[0], True, ["key_remote_jid", "jid_group.raw_string"], "jid", "android")}
                    {get_chat_condition(filter_chat[1], False, ["key_remote_jid", "jid_group.raw_string"], "jid", "android")}
                ORDER BY jid.raw_string ASC"""
        )
    content = c.fetchone()
    mime = MimeTypes()
    if not os.path.isdir(f"{media_folder}/thumbnails"):
        Path(f"{media_folder}/thumbnails").mkdir(parents=True, exist_ok=True)
    while content is not None:
        file_path = f"{media_folder}/{content['file_path']}"
        message = data[content["key_remote_jid"]].messages[content["message_row_id"]]
        message.media = True
        if os.path.isfile(file_path):
            message.data = file_path
            if content["mime_type"] is None:
                guess = mime.guess_type(file_path)[0]
                if guess is not None:
                    message.mime = guess
                else:
                    message.mime = "application/octet-stream"
            else:
                message.mime = content["mime_type"]
            if separate_media:
                chat_display_name = slugify(data[content["key_remote_jid"]].name or message.sender \
                                            or content["key_remote_jid"].split('@')[0], True)
                current_filename = file_path.split("/")[-1]
                new_folder = os.path.join(media_folder, "separated", chat_display_name)
                Path(new_folder).mkdir(parents=True, exist_ok=True)
                new_path = os.path.join(new_folder, current_filename)
                shutil.copy2(file_path, new_path)
                message.data = new_path
        else:
            message.data = "The media is missing"
            message.mime = "media"
            message.meta = True
        if content["thumbnail"] is not None:
            thumb_path = f"{media_folder}/thumbnails/{b64decode(content['file_hash']).hex()}.png"
            if not os.path.isfile(thumb_path):
                with open(thumb_path, "wb") as f:
                    f.write(content["thumbnail"])
            message.thumb = thumb_path
        i += 1
        if i % 100 == 0:
            print(f"Processing media...({i}/{total_row_number})", end="\r")
        content = c.fetchone()
    print(
        f"Processing media...({total_row_number}/{total_row_number})", end="\r")


def vcard(db, data, media_folder, filter_date, filter_chat):
    c = db.cursor()
    try:
        c.execute(f"""SELECT message_row_id,
                        messages.key_remote_jid,
                        vcard,
                        messages.media_name
                 FROM messages_vcards
                    INNER JOIN messages
                        ON messages_vcards.message_row_id = messages._id
                    INNER JOIN jid
                        ON messages.key_remote_jid = jid.raw_string
                 WHERE 1=1
                    {f'AND messages.timestamp {filter_date}' if filter_date is not None else ''}
                    {get_chat_condition(filter_chat[0], True, ["messages.key_remote_jid", "remote_resource"], "jid", "android")}
                    {get_chat_condition(filter_chat[1], False, ["messages.key_remote_jid", "remote_resource"], "jid", "android")}
                 ORDER BY messages.key_remote_jid ASC;"""
        )
    except sqlite3.OperationalError:
        c.execute(f"""SELECT message_row_id,
                        jid.raw_string as key_remote_jid,
                        vcard,
                        message.text_data as media_name
                 FROM message_vcard
                    INNER JOIN message
                        ON message_vcard.message_row_id = message._id
                    LEFT JOIN chat
                        ON chat._id = message.chat_row_id
                    INNER JOIN jid
                        ON jid._id = chat.jid_row_id
                    LEFT JOIN jid jid_group
                        ON jid_group._id = message.sender_jid_row_id
                WHERE 1=1
                    {f'AND message.timestamp {filter_date}' if filter_date is not None else ''}
                    {get_chat_condition(filter_chat[0], True, ["key_remote_jid", "jid_group.raw_string"], "jid", "android")}
                    {get_chat_condition(filter_chat[1], False, ["key_remote_jid", "jid_group.raw_string"], "jid", "android")}
                 ORDER BY message.chat_row_id ASC;"""
        )

    rows = c.fetchall()
    total_row_number = len(rows)
    print(f"\nProcessing vCards...(0/{total_row_number})", end="\r")
    path = f"{media_folder}/vCards"
    if not os.path.isdir(path):
        Path(path).mkdir(parents=True, exist_ok=True)
    for index, row in enumerate(rows):
        media_name = row["media_name"] if row["media_name"] is not None else "Undefined vCard File"
        file_name = "".join(x for x in media_name if x.isalnum())
        file_name = file_name.encode('utf-8')[:230].decode('utf-8', 'ignore')
        file_path = os.path.join(path, f"{file_name}.vcf")
        if not os.path.isfile(file_path):
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(row["vcard"])
        message = data[row["key_remote_jid"]].messages[row["message_row_id"]]
        message.data = "This media include the following vCard file(s):<br>" \
            f'<a href="{htmle(file_path)}">{htmle(media_name)}</a>'
        message.mime = "text/x-vcard"
        message.meta = True
        message.safe = True
        print(f"Processing vCards...({index + 1}/{total_row_number})", end="\r")


def calls(db, data, timezone_offset, filter_chat):
    c = db.cursor()
    c.execute(f"""SELECT count()
                FROM call_log
                    INNER JOIN jid
                        ON call_log.jid_row_id = jid._id
                    LEFT JOIN chat
                        ON call_log.jid_row_id = chat.jid_row_id
                WHERE 1=1
                    {get_chat_condition(filter_chat[0], True, ["jid.raw_string"])}
                    {get_chat_condition(filter_chat[1], False, ["jid.raw_string"])}""")
    total_row_number = c.fetchone()[0]
    if total_row_number == 0:
        return
    print(f"\nProcessing calls...({total_row_number})", end="\r")
    c.execute(f"""SELECT call_log._id,
                        jid.raw_string,
                        from_me,
                        call_id,
                        timestamp,
                        video_call,
                        duration,
                        call_result,
                        bytes_transferred,
                        chat.subject as chat_subject
                FROM call_log
                    INNER JOIN jid
                        ON call_log.jid_row_id = jid._id
                    LEFT JOIN chat
                        ON call_log.jid_row_id = chat.jid_row_id
                WHERE 1=1
                    {get_chat_condition(filter_chat[0], True, ["jid.raw_string"])}
                    {get_chat_condition(filter_chat[1], False, ["jid.raw_string"])}"""
    )
    chat = ChatStore(Device.ANDROID, "WhatsApp Calls")
    content = c.fetchone()
    while content is not None:
        call = Message(
            from_me=content["from_me"],
            timestamp=content["timestamp"],
            time=content["timestamp"],
            key_id=content["call_id"],
            timezone_offset=timezone_offset
        )
        _jid = content["raw_string"]
        name = data[_jid].name if _jid in data else content["chat_subject"] or None
        if _jid is not None and "@" in _jid:
            fallback = _jid.split('@')[0]
        else:
            fallback = None
        call.sender = name or fallback
        call.meta = True
        call.data = (
            f"A {'video' if content['video_call'] else 'voice'} "
            f"call {'to' if call.from_me else 'from'} "
            f"{call.sender} was "
        )
        if content['call_result'] in (0, 4, 7):
            call.data += "cancelled." if call.from_me else "missed."
        elif content['call_result'] == 2:
            call.data += "not answered." if call.from_me else "missed."
        elif content['call_result'] == 3:
            call.data += "unavailable."
        elif content['call_result'] == 5:
            call_time = convert_time_unit(content['duration'])
            call_bytes = bytes_to_readable(content['bytes_transferred'])
            call.data += (
                f"initiated and lasted for {call_time} "
                f"with {call_bytes} data transferred."
            )
        else:
            call.data += "in an unknown state."
        chat.add_message(content["_id"], call)
        content = c.fetchone()
    data["000000000000000"] = chat


def create_html(
        data,
        output_folder,
        template=None,
        embedded=False,
        offline_static=False,
        maximum_size=None,
        no_avatar=False,
        filter_empty=True
    ):
    template = setup_template(template, no_avatar)

    total_row_number = len(data)
    print(f"\nGenerating chats...(0/{total_row_number})", end="\r")

    if not os.path.isdir(output_folder):
        os.mkdir(output_folder)

    w3css = get_status_location(output_folder, offline_static)

    for current, contact in enumerate(data):
        chat = data[contact]
        if filter_empty and chat_is_empty(chat):
            continue
        safe_file_name, name = get_file_name(contact, chat)

        if maximum_size is not None:
            current_size = 0
            current_page = 1
            render_box = []
            if maximum_size == 0:
                maximum_size = MAX_SIZE
            last_msg = chat.get_last_message().key_id
            for message in chat.get_messages():
                if message.data is not None and not message.meta and not message.media:
                    current_size += len(message.data) + ROW_SIZE
                else:
                    current_size += ROW_SIZE + 100  # Assume media and meta HTML are 100 bytes
                if current_size > maximum_size:
                    output_file_name = f"{output_folder}/{safe_file_name}-{current_page}.html"
                    rendering(
                        output_file_name,
                        template,
                        name,
                        render_box,
                        contact,
                        w3css,
                        f"{safe_file_name}-{current_page + 1}.html",
                        chat
                    )
                    render_box = [message]
                    current_size = 0
                    current_page += 1
                else:
                    render_box.append(message)
                    if message.key_id == last_msg:
                        if current_page == 1:
                            output_file_name = f"{output_folder}/{safe_file_name}.html"
                        else:
                            output_file_name = f"{output_folder}/{safe_file_name}-{current_page}.html"
                        rendering(
                            output_file_name,
                            template,
                            name,
                            render_box,
                            contact,
                            w3css,
                            False,
                            chat
                        )
        else:
            output_file_name = f"{output_folder}/{safe_file_name}.html"
            rendering(
                output_file_name,
                template,
                name,
                chat.get_messages(),
                contact,
                w3css,
                False,
                chat
            )
        if current % 10 == 0:
            print(f"Generating chats...({current}/{total_row_number})", end="\r")

    print(f"Generating chats...({total_row_number}/{total_row_number})", end="\r")


def create_txt(data, output):
    os.makedirs(output, exist_ok=True)
    for jik, chat in data.items():
        if chat.name is not None:
            contact = chat.name.replace('/', '')
        else:
            contact = jik.replace('+', '')
        output_file = os.path.join(output, f"{contact}.txt")
        with open(output_file, "w", encoding="utf8") as f:
            for message in chat.messages.values():
                date = datetime.fromtimestamp(message.timestamp).date()
                if message.meta and message.mime != "media":
                    continue  # Skip any metadata in text format
                if message.from_me:
                    name = "You"
                else:
                    name = message.sender if message.sender else contact
                prefix = f"[{date} {message.time}] {name}: "
                prefix_length = len(prefix)
                if message.media and ("/" in message.mime or message.mime == "media"):
                    if message.data == "The media is missing":
                        message_text = "<The media is missing>"
                    else:
                        message_text = f"<media file in {message.data}>"
                else:
                    if message.data is None:
                        message_text = ""
                    else:
                        message_text = message.data.replace('<br>', f'\n{" " * prefix_length}')
                if message.caption is not None:
                    message_text += "\n" + ' ' * len(prefix) + message.caption.replace('<br>', f'\n{" " * prefix_length}')
                f.write(f"{prefix}{message_text}\n")

