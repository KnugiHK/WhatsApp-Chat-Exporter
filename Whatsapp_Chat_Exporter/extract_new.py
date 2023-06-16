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
from bleach import clean as sanitize
from markupsafe import Markup
from datetime import datetime
from enum import Enum
from mimetypes import MimeTypes
from hashlib import sha256

from Whatsapp_Chat_Exporter.data_model import ChatStore, Message

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


def sanitize_except(html):
    return Markup(sanitize(html, tags=["br"]))


def determine_day(last, current):
    last = datetime.fromtimestamp(last).date()
    current = datetime.fromtimestamp(current).date()
    if last == current:
        return None
    else:
        return current


CRYPT14_OFFSETS = (
    {"iv": 67, "db": 191},
    {"iv": 67, "db": 190},
    {"iv": 66, "db": 99},
    {"iv": 67, "db": 193}
)


class Crypt(Enum):
    CRYPT15 = 15
    CRYPT14 = 14
    CRYPT12 = 12


def brute_force_offset():
    for iv in range(0, 200):
        for db in range(0, 200):
            yield iv, iv + 16, db


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
        db_offset = database[0] + 2 # Skip protobuf + protobuf size and backup type
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
                                "https://github.com/KnugiHK/Whatsapp-Chat-Exporter/issues/new"
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
    print(f"Gathering contacts...({total_row_number})")

    c.execute("""SELECT jid, display_name FROM wa_contacts; """)
    row = c.fetchone()
    while row is not None:
        data[row["jid"]] = ChatStore(row["display_name"])
        row = c.fetchone()


def messages(db, data):
    # Get message history
    c = db.cursor()
    c.execute("""SELECT count() FROM message""")
    total_row_number = c.fetchone()[0]
    print(f"Gathering messages...(0/{total_row_number})", end="\r")

    phone_number_re = re.compile(r"[0-9]+@s.whatsapp.net")
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
                    WHERE key_remote_jid <> '-1';""")
    i = 0
    content = c.fetchone()
    while content is not None:
        if content["key_remote_jid"] not in data:
            data[content["key_remote_jid"]] = ChatStore()
        if content["key_remote_jid"] is None:
            continue
        data[content["key_remote_jid"]].add_message(content["_id"], Message(
            from_me=content["key_from_me"],
            timestamp=content["timestamp"],
            time=content["timestamp"],
            key_id=content["key_id"],
        ))
        if "-" in content["key_remote_jid"] and content["key_from_me"] == 0:
            name = None
            if content["chat_subject"] is not None:
                _jid = content["group_sender_jid"]
            else:
                _jid = content["key_remote_jid"]
            if _jid in data:
                name = data[_jid].name
                fallback = _jid.split('@')[0] if "@" in _jid else None
            else:
                fallback = None
            data[content["key_remote_jid"]].messages[content["_id"]].sender = name or fallback
        else:
            data[content["key_remote_jid"]].messages[content["_id"]].sender = None

        if content["quoted"] is not None:
            data[content["key_remote_jid"]].messages[content["_id"]].reply = content["quoted"]
            data[content["key_remote_jid"]].messages[content["_id"]].quoted_data = content["quoted_data"]
        else:
            data[content["key_remote_jid"]].messages[content["_id"]].reply = None

        if content["message_type"] == 1:
            data[content["key_remote_jid"]].messages[content["_id"]].caption = content["data"]
        else:
            data[content["key_remote_jid"]].messages[content["_id"]].caption = None

        if content["status"] == 6:
            if content["chat_subject"] is not None:
                # Is Group
                if content["data"] is not None:
                    try:
                        int(content["data"])
                    except ValueError:
                        msg = f"The group name changed to {content['data']}"
                        data[content["key_remote_jid"]].messages[content["_id"]].data = msg
                        data[content["key_remote_jid"]].messages[content["_id"]].meta = True
                    else:
                        data[content["key_remote_jid"]].delete_message(content["_id"])
                else:
                    thumb_image = content["thumb_image"]
                    if thumb_image is not None:
                        if b"\x00\x00\x01\x74\x00\x1A" in thumb_image:
                            # Add user
                            added = phone_number_re.search(
                                thumb_image.decode("unicode_escape"))[0]
                            if added in data:
                                name_right = data[added]["name"]
                            else:
                                name_right = added.split('@')[0]
                            if content["remote_resource"] is not None:
                                if content["remote_resource"] in data:
                                    name_left = data[content["remote_resource"]]["name"]
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
                        data[content["key_remote_jid"]].messages[content["_id"]].data = msg
                        data[content["key_remote_jid"]].messages[content["_id"]].meta = True
                    else:
                        if content["data"] is None:
                            data[content["key_remote_jid"]].delete_message(content["_id"])
            else:
                # Private chat
                if content["data"] is None and content["thumb_image"] is None:
                    data[content["key_remote_jid"]].delete_message(content["_id"])

        else:
            if content["key_from_me"] == 1:
                if content["status"] == 5 and content["edit_version"] == 7:
                    msg = "Message deleted"
                    data[content["key_remote_jid"]].messages[content["_id"]].meta = True
                else:
                    if content["media_wa_type"] == "5":
                        msg = f"Location shared: {content[10], content[11]}"
                        data[content["key_remote_jid"]].messages[content["_id"]].meta = True
                    else:
                        msg = content["data"]
                        if msg is not None:
                            if "\r\n" in msg:
                                msg = msg.replace("\r\n", "<br>")
                            if "\n" in msg:
                                msg = msg.replace("\n", "<br>")
            else:
                if content["status"] == 0 and content["edit_version"] == 7:
                    msg = "Message deleted"
                    data[content["key_remote_jid"]].messages[content["_id"]].meta = True
                else:
                    if content["media_wa_type"] == "5":
                        msg = f"Location shared: {content[10], content[11]}"
                        data[content["key_remote_jid"]].messages[content["_id"]].meta = True
                    else:
                        msg = content["data"]
                        if msg is not None:
                            if "\r\n" in msg:
                                msg = msg.replace("\r\n", "<br>")
                            if "\n" in msg:
                                msg = msg.replace("\n", "<br>")

            data[content["key_remote_jid"]].messages[content["_id"]].data = msg

        i += 1
        if i % 1000 == 0:
            print(f"Gathering messages...({i}/{total_row_number})", end="\r")
        content = c.fetchone()
    print(f"Gathering messages...({total_row_number}/{total_row_number})", end="\r")


def media(db, data, media_folder):
    # Get media
    c = db.cursor()
    c.execute("""SELECT count() FROM message_media""")
    total_row_number = c.fetchone()[0]
    print(f"\nGathering media...(0/{total_row_number})", end="\r")
    i = 0
    c.execute("""SELECT jid.raw_string,
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
                 ORDER BY jid.raw_string ASC""")
    content = c.fetchone()
    mime = MimeTypes()
    while content is not None:
        file_path = f"{media_folder}/{content['file_path']}"
        data[content["raw_string"]].messages[content["message_row_id"]].media = True
        if os.path.isfile(file_path):
            data[content["raw_string"]].messages[content["message_row_id"]].data = file_path
            if content["mime_type"] is None:
                guess = mime.guess_type(file_path)[0]
                if guess is not None:
                    data[content["raw_string"]].messages[content["message_row_id"]].mime = guess
                else:
                    data[content["raw_string"]].messages[content["message_row_id"]].mime = "data/data"
            else:
                data[content["raw_string"]].messages[content["message_row_id"]].mime = content["mime_type"]
        else:
            # if "https://mmg" in content["mime_type"]:
            # try:
            # r = requests.get(content["message_url"])
            # if r.status_code != 200:
            # raise RuntimeError()
            # except:
            # data[content["raw_string"]].messages[content["message_row_id"]].data = "{The media is missing}"
            # data[content["raw_string"]].messages[content["message_row_id"]].media = True
            # data[content["raw_string"]].messages[content["message_row_id"]].mime = "media"
            # else:
            data[content["raw_string"]].messages[content["message_row_id"]].data = "The media is missing"
            data[content["raw_string"]].messages[content["message_row_id"]].mime = "media"
            data[content["raw_string"]].messages[content["message_row_id"]].meta = True
        i += 1
        if i % 100 == 0:
            print(f"Gathering media...({i}/{total_row_number})", end="\r")
        content = c.fetchone()
    print(
        f"Gathering media...({total_row_number}/{total_row_number})", end="\r")


def vcard(db, data):
    c = db.cursor()
    c.execute("""SELECT message_row_id,
                        jid.raw_string,
                        vcard,
                        message.text_data
                 FROM message_vcard
                    INNER JOIN message
                        ON message_vcard.message_row_id = message._id
                    LEFT JOIN chat
                        ON chat._id = message.chat_row_id
                    INNER JOIN jid
                        ON jid._id = chat.jid_row_id
                 ORDER BY message.chat_row_id ASC;""")
    rows = c.fetchall()
    total_row_number = len(rows)
    print(f"\nGathering vCards...(0/{total_row_number})", end="\r")
    base = "WhatsApp/vCards"
    if not os.path.isdir(base):
        Path(base).mkdir(parents=True, exist_ok=True)
    for index, row in enumerate(rows):
        media_name = row["text_data"] if row["text_data"] else ""
        file_name = "".join(x for x in media_name if x.isalnum())
        file_path = f"{base}/{file_name}.vcf"
        if not os.path.isfile(file_path):
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(row["vcard"])
        data[row["raw_string"]].messages[row["message_row_id"]].data = media_name + \
            "The vCard file cannot be displayed here, " \
            f"however it should be located at {file_path}"
        data[row["raw_string"]].messages[row["message_row_id"]].mime = "text/x-vcard"
        data[row["raw_string"]].messages[row["message_row_id"]].meta = True
        print(f"Gathering vCards...({index + 1}/{total_row_number})", end="\r")


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
                with open(w3css_path, "wb") as f: f.write(resp.read())
        w3css = os.path.join(offline_static, "w3.css")

    for current, contact in enumerate(data):
        if len(data[contact].messages) == 0:
            continue
        phone_number = contact.split('@')[0]
        if "-" in contact:
            file_name = ""
        else:
            file_name = phone_number

        if data[contact].name is not None:
            if file_name != "":
                file_name += "-"
            file_name += data[contact].name.replace("/", "-")
            name = data[contact].name
        else:
            name = phone_number

        safe_file_name = "".join(x for x in file_name if x.isalnum() or x in "- ")
        with open(f"{output_folder}/{safe_file_name}.html", "w", encoding="utf-8") as f:
            f.write(
                template.render(
                    name=name,
                    msgs=data[contact].messages.values(),
                    my_avatar=None,
                    their_avatar=f"WhatsApp/Avatars/{contact}.j",
                    w3css=w3css
                )
            )
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
