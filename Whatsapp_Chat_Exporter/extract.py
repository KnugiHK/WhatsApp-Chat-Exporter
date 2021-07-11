#!/usr/bin/python3

import sqlite3
import json
import jinja2
import os
import requests
import shutil
import re
import pkgutil
from bleach import clean as sanitize
from markupsafe import Markup
from datetime import datetime
from mimetypes import MimeTypes
try:
    import zlib
    from Crypto.Cipher import AES
except ModuleNotFoundError:
    support_backup = False
else:
    support_backup = True


def sanitize_except(html):
    return Markup(sanitize(html, tags=["br"]))


def determine_day(last, current):
    last = datetime.fromtimestamp(last).date()
    current = datetime.fromtimestamp(current).date()
    if last == current:
        return None
    else:
        return current


def decrypt_backup(database, key, output, crypt14=True):
    if not support_backup:
        return False
    if len(key) != 158:
        raise ValueError("The key file must be 158 bytes")
    t1 = key[30:62]
    if crypt14:
        if len(database) < 191:
            raise ValueError("The crypt14 file must be at least 191 bytes")
        t2 = database[15:47]
        iv = database[67:83]
        db_ciphertext = database[191:]
    else:
        if len(database) < 67:
            raise ValueError("The crypt12 file must be at least 67 bytes")
        t2 = database[3:35]
        iv = database[51:67]
        db_ciphertext = database[67:-20]
    if t1 != t2:
        raise ValueError("The signature of key file and backup file mismatch")

    main_key = key[126:]
    cipher = AES.new(main_key, AES.MODE_GCM, iv)
    db_compressed = cipher.decrypt(db_ciphertext)
    db = zlib.decompress(db_compressed)
    if db[0:6].upper() == b"SQLITE":
        with open(output, "wb") as f:
            f.write(db)
        return True
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
        data[row[0]] = {"name": row[1], "messages": {}}
        row = c.fetchone()


def messages(db, data):
    # Get message history
    c = db.cursor()
    c.execute("""SELECT count() FROM messages""")
    total_row_number = c.fetchone()[0]
    print(f"Gathering messages...(0/{total_row_number})", end="\r")

    phone_number_re = re.compile(r"[0-9]+@s.whatsapp.net")
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
                        messages_quotes.data,
                        messages.media_caption
                 FROM messages
                    LEFT JOIN messages_quotes
                        ON messages.quoted_row_id = messages_quotes._id;""")
    i = 0
    content = c.fetchone()
    while content is not None:
        if content[0] not in data:
            data[content[0]] = {"name": None, "messages": {}}
        data[content[0]]["messages"][content[1]] = {
            "from_me": bool(content[2]),
            "timestamp": content[3]/1000,
            "time": datetime.fromtimestamp(content[3]/1000).strftime("%H:%M"),
            "media": False,
            "key_id": content[13]
        }
        if "-" in content[0] and content[2] == 0:
            name = None
            if content[8] in data:
                name = data[content[8]]["name"]
                if "@" in content[8]:
                    fallback = content[8].split('@')[0]
                else:
                    fallback = None
            else:
                fallback = None

            data[content[0]]["messages"][content[1]]["sender"] = name or fallback
        else:
            data[content[0]]["messages"][content[1]]["sender"] = None

        if content[12] is not None:
            data[content[0]]["messages"][content[1]]["reply"] = content[12]
            data[content[0]]["messages"][content[1]]["quoted_data"] = content[14]
        else:
            data[content[0]]["messages"][content[1]]["reply"] = None

        if content[15] is not None:
            data[content[0]]["messages"][content[1]]["caption"] = content[15]
        else:
            data[content[0]]["messages"][content[1]]["caption"] = None

        if content[5] == 6:
            if "-" in content[0]:
                # Is Group
                if content[4] is not None:
                    try:
                        int(content[4])
                    except ValueError:
                        msg = "{The group name changed to "f"{content[4]}"" }"
                        data[content[0]]["messages"][content[1]]["data"] = msg
                    else:
                        del data[content[0]]["messages"][content[1]]
                else:
                    thumb_image = content[7]
                    if thumb_image is not None:
                        if b"\x00\x00\x01\x74\x00\x1A" in thumb_image:
                            # Add user
                            added = phone_number_re.search(
                                thumb_image.decode("unicode_escape"))[0]
                            if added in data:
                                name_right = data[added]["name"]
                            else:
                                name_right = added.split('@')[0]
                            if content[8] is not None:
                                if content[8] in data:
                                    name_left = data[content[8]]["name"]
                                else:
                                    name_left = content[8].split('@')[0]
                                msg = "{"f"{name_left}"f" added {name_right or 'You'}""}"
                            else:
                                msg = "{"f"Added {name_right or 'You'}""}"
                        elif b"\xac\xed\x00\x05\x74\x00" in thumb_image:
                            # Changed number
                            original = content[8].split('@')[0]
                            changed = thumb_image[7:].decode().split('@')[0]
                            msg = "{"f"{original} changed to {changed}""}"
                        data[content[0]]["messages"][content[1]]["data"] = msg
                    else:
                        if content[4] is None:
                            del data[content[0]]["messages"][content[1]]
            else:
                # Private chat
                if content[4] is None and content[7] is None:
                    del data[content[0]]["messages"][content[1]]

        else:
            if content[2] == 1:
                if content[5] == 5 and content[6] == 7:
                    msg = "{Message deleted}"
                else:
                    if content[9] == "5":
                        msg = "{ Location shared: "f"{content[10], content[11]}"" }"
                    else:
                        msg = content[4]
                        if msg is not None:
                            if "\r\n" in msg:
                                msg = msg.replace("\r\n", "<br>")
                            if "\n" in msg:
                                msg = msg.replace("\n", "<br>")
            else:
                if content[5] == 0 and content[6] == 7:
                    msg = "{Message deleted}"
                else:
                    if content[9] == "5":
                        msg = "{ Location shared: "f"{content[10], content[11]}"" }"
                    else:
                        msg = content[4]
                        if msg is not None:
                            if "\r\n" in msg:
                                msg = msg.replace("\r\n", "<br>")
                            if "\n" in msg:
                                msg = msg.replace("\n", "<br>")

            data[content[0]]["messages"][content[1]]["data"] = msg

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
    c.execute("""SELECT messages.key_remote_jid,
                        message_row_id,
                        file_path,
                        message_url,
                        mime_type,
                        media_key
                 FROM message_media
                    INNER JOIN messages
                        ON message_media.message_row_id = messages._id
                ORDER BY messages.key_remote_jid ASC""")
    content = c.fetchone()
    mime = MimeTypes()
    while content is not None:
        file_path = f"{media_folder}/{content[2]}"
        data[content[0]]["messages"][content[1]]["media"] = True
        if os.path.isfile(file_path):
            data[content[0]]["messages"][content[1]]["data"] = file_path
            if content[4] is None:
                guess = mime.guess_type(file_path)[0]
                if guess is not None:
                    data[content[0]]["messages"][content[1]]["mime"] = guess
                else:
                    data[content[0]]["messages"][content[1]]["mime"] = "data/data"
            else:
                data[content[0]]["messages"][content[1]]["mime"] = content[4]
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
            data[content[0]]["messages"][content[1]]["data"] = "{The media is missing}"
            data[content[0]]["messages"][content[1]]["mime"] = "media"
        i += 1
        if i % 100 == 0:
            print(f"Gathering media...({i}/{total_row_number})", end="\r")
        content = c.fetchone()
    print(
        f"Gathering media...({total_row_number}/{total_row_number})", end="\r")


def vcard(db, data):
    c = db.cursor()
    c.execute("""SELECT message_row_id,
                        messages.key_remote_jid,
                        vcard,
                        messages.media_name
                 FROM messages_vcards
                    INNER JOIN messages
                        ON messages_vcards.message_row_id = messages._id
                 ORDER BY messages.key_remote_jid ASC;""")
    rows = c.fetchall()
    total_row_number = len(rows)
    print(f"\nGathering vCards...(0/{total_row_number})", end="\r")
    base = "WhatsApp/vCards"
    for index, row in enumerate(rows):
        if not os.path.isdir(base):
            os.mkdir(base)
        file_name = "".join(x for x in row[3] if x.isalnum())
        file_path = f"{base}/{file_name}.vcf"
        if not os.path.isfile(file_path):
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(row[2])
        data[row[1]]["messages"][row[0]]["data"] = row[3] + \
            "{ The vCard file cannot be displayed here, however it " \
            "should be located at " + file_path + "}"
        data[row[1]]["messages"][row[0]]["mime"] = "text/x-vcard"
        print(f"Gathering vCards...({index + 1}/{total_row_number})", end="\r")


def create_html(data, output_folder, template=None):
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

    for current, contact in enumerate(data):
        if len(data[contact]["messages"]) == 0:
            continue
        phone_number = contact.split('@')[0]
        if "-" in contact:
            file_name = ""
        else:
            file_name = phone_number

        if data[contact]["name"] is not None:
            if file_name != "":
                file_name += "-"
            file_name += data[contact]["name"].replace("/", "-")
            name = data[contact]["name"]
        else:
            name = phone_number
        safe_file_name = ''
        safe_file_name = "".join(x for x in file_name if x.isalnum() or x in "- ")
        with open(f"{output_folder}/{safe_file_name}.html", "w", encoding="utf-8") as f:
            f.write(
                template.render(
                    name=name,
                    msgs=data[contact]["messages"].values(),
                    my_avatar=None,
                    their_avatar=f"WhatsApp/Avatars/{contact}.j"
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
