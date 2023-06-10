#!/usr/bin/python3

import sqlite3
import json
import jinja2
import os
import shutil
import re
import io
import hmac
from pathlib import Path
from mimetypes import MimeTypes
from hashlib import sha256
from Whatsapp_Chat_Exporter.data_model import ChatStore, Message
from Whatsapp_Chat_Exporter.utility import MAX_SIZE, ROW_SIZE, rendering, sanitize_except, determine_day, Crypt
from Whatsapp_Chat_Exporter.utility import brute_force_offset, CRYPT14_OFFSETS

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


def decrypt_backup(database, key, output, crypt=Crypt.CRYPT14, show_crypt15=False):
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
        iv = database[8:24]
        db_offset = database[0] + 2  # Skip protobuf + protobuf size and backup type
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
    print(f"Processing contacts...({total_row_number})")

    c.execute("""SELECT jid, display_name FROM wa_contacts; """)
    row = c.fetchone()
    while row is not None:
        data[row["jid"]] = ChatStore(row["display_name"])
        row = c.fetchone()


def messages(db, data):
    # Get message history
    c = db.cursor()
    try:
        c.execute("""SELECT count() FROM messages""")
    except sqlite3.OperationalError:
        c.execute("""SELECT count() FROM message""")
    total_row_number = c.fetchone()[0]
    print(f"Processing messages...(0/{total_row_number})", end="\r")

    phone_number_re = re.compile(r"[0-9]+@s.whatsapp.net")
    try:
        c.execute("""SELECT messages.key_remote_jid,
                            messages._id,
                            messages.key_from_me,
                            messages.timestamp,
                            messages.data,
                            messages.status,
                            messages.edit_version,
                            messages.thumb_image,
                            messages.remote_resource,
                            messages.media_wa_type,
                            messages.latitude,
                            messages.longitude,
                            messages_quotes.key_id as quoted,
                            messages.key_id,
                            messages_quotes.data as quoted_data,
                            messages.media_caption
                    FROM messages
                        LEFT JOIN messages_quotes
                            ON messages.quoted_row_id = messages_quotes._id
                    WHERE messages.key_remote_jid <> '-1';"""
        )
    except sqlite3.OperationalError:
        try:
            c.execute("""SELECT jid_global.raw_string as key_remote_jid,
                            message._id,
                            message.from_me as key_from_me,
                            message.timestamp,
                            message.text_data as data,
                            message.status,
                            message_future.version as edit_version,
                            message_thumbnail.thumbnail as thumb_image,
                            message_media.file_path as remote_resource,
                            message_media.mime_type as media_wa_type,
                            message_location.latitude,
                            message_location.longitude,
                            message_quoted.key_id as quoted,
                            message.key_id,
                            message_quoted.text_data as quoted_data,
                            message.message_type,
                            jid_group.raw_string as group_sender_jid,
                            chat.subject as chat_subject
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
                        WHERE key_remote_jid <> '-1';"""
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
            if content is not None and isinstance(content["data"], bytes):
                continue
            break
    while content is not None:
        if content["key_remote_jid"] not in data:
            data[content["key_remote_jid"]] = ChatStore()
        if content["key_remote_jid"] is None:
            continue  # Not sure
        message = Message(
            from_me=content["key_from_me"],
            timestamp=content["timestamp"],
            time=content["timestamp"],
            key_id=content["key_id"],
        )
        invalid = False
        if "-" in content["key_remote_jid"] and content["key_from_me"] == 0:
            name = None
            if table_message:
                if content["chat_subject"] is not None:
                    _jid = content["group_sender_jid"]
                else:
                    _jid = content["key_remote_jid"]
                if _jid in data:
                    name = data[_jid].name
                    fallback = _jid.split('@')[0] if "@" in _jid else None
                else:
                    fallback = None
            else:
                if content["remote_resource"] in data:
                    name = data[content["remote_resource"]].name
                    if "@" in content["remote_resource"]:
                        fallback = content["remote_resource"].split('@')[0]
                    else:
                        fallback = None
                else:
                    fallback = None

            message.sender = name or fallback
        else:
            message.sender = None

        if content["quoted"] is not None:
            message.reply = content["quoted"]
            message.quoted_data = content["quoted_data"]
        else:
            message.reply = None

        if not table_message and content["media_caption"] is not None:
            # Old schema
            message.caption = content["media_caption"]
        elif table_message and content["message_type"] == 1 and content["data"] is not None:
            # New schema
            message.caption = content["data"]
        else:
            message.caption = None

        if content["status"] == 6:  # 6 = Metadata, otherwise it's a message
            if (not table_message and "-" in content["key_remote_jid"]) or \
               (table_message and content["chat_subject"] is not None):
                # Is Group
                if content["data"] is not None:
                    try:
                        int(content["data"])
                    except ValueError:
                        msg = f"The group name changed to {content['data']}"
                        message.data = msg
                        message.meta = True
                    else:
                        invalid = True
                else:
                    thumb_image = content["thumb_image"]
                    if thumb_image is not None:
                        if b"\x00\x00\x01\x74\x00\x1A" in thumb_image:
                            # Add user
                            added = phone_number_re.search(
                                thumb_image.decode("unicode_escape"))[0]
                            if added in data:
                                name_right = data[added].name
                            else:
                                name_right = added.split('@')[0]
                            if content["remote_resource"] is not None:
                                if content["remote_resource"] in data:
                                    name_left = data[content["remote_resource"]].name
                                else:
                                    name_left = content["remote_resource"].split('@')[0]
                                msg = f"{name_left} added {name_right or 'You'}"
                            else:
                                msg = f"Added {name_right or 'You'}"
                        elif b"\xac\xed\x00\x05\x74\x00" in thumb_image:
                            # Changed number
                            original = content["remote_resource"].split('@')[0]
                            changed = thumb_image[7:].decode().split('@')[0]
                            msg = f"{original} changed to {changed}"
                        message.data = msg
                        message.meta = True
                    else:
                        if content["data"] is None:
                            invalid = True
            else:
                # Private chat
                if content["data"] is None and content["thumb_image"] is None:
                    invalid = True

        else:
            if content["key_from_me"] == 1:
                if content["status"] == 5 and content["edit_version"] == 7 or table_message and content["message_type"] == 15:
                    msg = "Message deleted"
                    message.meta = True
                else:
                    if content["media_wa_type"] == "5":
                        msg = f"Location shared: {content['latitude'], content['longitude']}"
                        message.meta = True
                    else:
                        msg = content["data"]
                        if msg is not None:
                            if "\r\n" in msg:
                                msg = msg.replace("\r\n", "<br>")
                            if "\n" in msg:
                                msg = msg.replace("\n", "<br>")
            else:
                if content["status"] == 0 and content["edit_version"] == 7 or table_message and content["message_type"] == 15:
                    msg = "Message deleted"
                    message.meta = True
                else:
                    if content["media_wa_type"] == "5":
                        msg = f"Location shared: {content['latitude'], content['longitude']}"
                        message.meta = True
                    else:
                        msg = content["data"]
                        if msg is not None:
                            if "\r\n" in msg:
                                msg = msg.replace("\r\n", "<br>")
                            if "\n" in msg:
                                msg = msg.replace("\n", "<br>")
            message.data = msg

        if not invalid:
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
                if content is not None and isinstance(content["data"], bytes):
                    continue
                break
    print(f"Processing messages...({total_row_number}/{total_row_number})", end="\r")


def media(db, data, media_folder):
    # Get media
    c = db.cursor()
    c.execute("""SELECT count() FROM message_media""")
    total_row_number = c.fetchone()[0]
    print(f"\nProcessing media...(0/{total_row_number})", end="\r")
    i = 0
    try:
        c.execute("""SELECT messages.key_remote_jid,
                        message_row_id,
                        file_path,
                        message_url,
                        mime_type,
                        media_key
                 FROM message_media
                    INNER JOIN messages
                        ON message_media.message_row_id = messages._id
                ORDER BY messages.key_remote_jid ASC"""
        )
    except sqlite3.OperationalError:
        c.execute("""SELECT jid.raw_string as key_remote_jid,
                    message_row_id,
                    file_path,
                    message_url,
                    mime_type,
                    media_key
                FROM message_media
                INNER JOIN message
                    ON message_media.message_row_id = message._id
                LEFT JOIN chat
                    ON chat._id = message.chat_row_id
                INNER JOIN jid
                    ON jid._id = chat.jid_row_id
                ORDER BY jid.raw_string ASC"""
        )
    content = c.fetchone()
    mime = MimeTypes()
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
        else:
            # if "https://mmg" in content[4]:
            # try:
            # r = requests.get(content[3])
            # if r.status_code != 200:
            # raise RuntimeError()
            # except:
            # data[content[0]]["messages"][content[1]]["data"] = "{The media is missing}"
            # data[content[0]]["messages"][content[1]]["media"] = True
            # data[content[0]]["messages"][content[1]]["mime"] = "media"
            # else:
            message.data = "The media is missing"
            message.mime = "media"
            message.meta = True
        i += 1
        if i % 100 == 0:
            print(f"Processing media...({i}/{total_row_number})", end="\r")
        content = c.fetchone()
    print(
        f"Processing media...({total_row_number}/{total_row_number})", end="\r")


def vcard(db, data):
    c = db.cursor()
    try:
        c.execute("""SELECT message_row_id,
                        messages.key_remote_jid,
                        vcard,
                        messages.media_name
                 FROM messages_vcards
                    INNER JOIN messages
                        ON messages_vcards.message_row_id = messages._id
                 ORDER BY messages.key_remote_jid ASC;"""
        )
    except sqlite3.OperationalError:
        c.execute("""SELECT message_row_id,
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
                 ORDER BY message.chat_row_id ASC;"""
        )

    rows = c.fetchall()
    total_row_number = len(rows)
    print(f"\nProcessing vCards...(0/{total_row_number})", end="\r")
    base = "WhatsApp/vCards"
    if not os.path.isdir(base):
        Path(base).mkdir(parents=True, exist_ok=True)
    for index, row in enumerate(rows):
        media_name = row["media_name"] if row["media_name"] is not None else ""
        file_name = "".join(x for x in media_name if x.isalnum())
        file_name = file_name.encode('utf-8')[:251].decode('utf-8', 'ignore')
        file_path = os.path.join(base, f"{file_name}.vcf")
        if not os.path.isfile(file_path):
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(row["vcard"])
        message = data[row["key_remote_jid"]].messages[row["message_row_id"]]
        message.data = media_name + \
            "The vCard file cannot be displayed here, " \
            f"however it should be located at {file_path}"
        message.mime = "text/x-vcard"
        message.meta = True
        print(f"Processing vCards...({index + 1}/{total_row_number})", end="\r")


def create_html(
        data,
        output_folder,
        template=None,
        embedded=False,
        offline_static=False,
        maximum_size=None
    ):
    if template is None:
        template_dir = os.path.dirname(__file__)
        template_file = "whatsapp.html"
    else:
        template_dir = os.path.dirname(template)
        template_file = os.path.basename(template)
    templateLoader = jinja2.FileSystemLoader(searchpath=template_dir)
    templateEnv = jinja2.Environment(loader=templateLoader)
    templateEnv.globals.update(determine_day=determine_day)
    templateEnv.filters['sanitize_except'] = sanitize_except
    template = templateEnv.get_template(template_file)

    total_row_number = len(data)
    print(f"\nCreating HTML...(0/{total_row_number})", end="\r")

    if not os.path.isdir(output_folder):
        os.mkdir(output_folder)

    w3css = "https://www.w3schools.com/w3css/4/w3.css"
    if offline_static:
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

    for current, contact in enumerate(data):
        chat = data[contact]
        if len(chat.messages) == 0:
            continue
        phone_number = contact.split('@')[0]
        if "-" in contact:
            file_name = ""
        else:
            file_name = phone_number

        if chat.name is not None:
            if file_name != "":
                file_name += "-"
            file_name += chat.name.replace("/", "-")
            name = chat.name
        else:
            name = phone_number

        safe_file_name = "".join(x for x in file_name if x.isalnum() or x in "- ")

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
                        f"{safe_file_name}-{current_page + 1}.html"
                    )
                    render_box = [message]
                    current_size = 0
                    current_page += 1
                else:
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
                            False
                        )
                    else:
                        render_box.append(message)
        else:
            output_file_name = f"{output_folder}/{safe_file_name}.html"
            rendering(output_file_name, template, name, chat.get_messages(), contact, w3css, False)
        if current % 10 == 0:
            print(f"Creating HTML...({current}/{total_row_number})", end="\r")

    print(f"Creating HTML...({total_row_number}/{total_row_number})", end="\r")


if __name__ == "__main__":
    from optparse import OptionParser
    parser = OptionParser()
    parser.add_option(
        "-w",
        "--wa",
        dest="wa",
        default="wa.db",
        help="Path to contact database")
    parser.add_option(
        "-m",
        "--media",
        dest="media",
        default="WhatsApp",
        help="Path to WhatsApp media folder"
    )
    # parser.add_option(
    #     "-t",
    #     "--template",
    #     dest="html",
    #     default="wa.db",
    #     help="Path to HTML template")
    (options, args) = parser.parse_args()
    msg_db = "msgstore.db"
    output_folder = "temp"
    contact_db = options.wa
    media_folder = options.media

    if len(args) == 1:
        msg_db = args[0]
    elif len(args) == 2:
        msg_db = args[0]
        output_folder = args[1]

    data = {}

    if os.path.isfile(contact_db):
        with sqlite3.connect(contact_db) as db:
            contacts(db, data)
    if os.path.isfile(msg_db):
        with sqlite3.connect(msg_db) as db:
            messages(db, data)
            media(db, data, media_folder)
            vcard(db, data)
        create_html(data, output_folder)

    if not os.path.isdir(f"{output_folder}/WhatsApp"):
        shutil.move(media_folder, f"{output_folder}/")

    with open("result.json", "w") as f:
        data = json.dumps(data)
        print(f"\nWriting JSON file...({int(len(data)/1024/1024)}MB)")
        f.write(data)

    print("Everything is done!")
