#!/usr/bin/python3

import sqlite3
import json
import string
import jinja2
import os
import shutil
from pathlib import Path
from datetime import datetime
from mimetypes import MimeTypes
from Whatsapp_Chat_Exporter.data_model import ChatStore, Message
from Whatsapp_Chat_Exporter.utility import sanitize_except, determine_day, APPLE_TIME


def messages(db, data):
    c = db.cursor()
    # Get contacts
    c.execute("""SELECT count() FROM ZWACHATSESSION""")
    total_row_number = c.fetchone()[0]
    print(f"Gathering contacts...({total_row_number})")

    c.execute("""SELECT ZCONTACTJID, ZPARTNERNAME FROM ZWACHATSESSION; """)
    content = c.fetchone()
    while content is not None:
        data[content["ZCONTACTJID"]] = ChatStore(content["ZPARTNERNAME"])
        content = c.fetchone()

    # Get message history
    c.execute("""SELECT count() FROM ZWAMESSAGE""")
    total_row_number = c.fetchone()[0]
    print(f"Gathering messages...(0/{total_row_number})", end="\r")

    c.execute("""SELECT COALESCE(ZFROMJID, ZTOJID) as _id,
                        ZWAMESSAGE.Z_PK,
                        ZISFROMME,
                        ZMESSAGEDATE,
                        ZTEXT,
                        ZMESSAGETYPE,
                        ZWAGROUPMEMBER.ZMEMBERJID,
						ZMETADATA,
                        ZSTANZAID
                 FROM ZWAMESSAGE
                    LEFT JOIN ZWAGROUPMEMBER
                        ON ZWAMESSAGE.ZGROUPMEMBER = ZWAGROUPMEMBER.Z_PK
					LEFT JOIN ZWAMEDIAITEM
						ON ZWAMESSAGE.Z_PK = ZWAMEDIAITEM.ZMESSAGE;""")
    i = 0
    content = c.fetchone()
    while content is not None:
        _id = content["_id"]
        Z_PK = content["Z_PK"]
        if _id not in data:
            data[_id] = ChatStore()
        ts = APPLE_TIME + content["ZMESSAGEDATE"]
        data[_id].add_message(Z_PK, Message(
            from_me=content["ZISFROMME"],
            timestamp=ts,
            time=ts, # Could be bug
            key_id=content["ZSTANZAID"][:17],
        ))
        if "-" in _id and content["ZISFROMME"] == 0:
            name = None
            if content["ZMEMBERJID"] is not None:
                if content["ZMEMBERJID"] in data:
                    name = data[content["ZMEMBERJID"]].name
                if "@" in content["ZMEMBERJID"]:
                    fallback = content["ZMEMBERJID"].split('@')[0]
                else:
                    fallback = None
            else:
                fallback = None
            data[_id].messages[Z_PK].sender = name or fallback
        else:
            data[_id].messages[Z_PK].sender = None
        if content["ZMESSAGETYPE"] == 6:
            # Metadata
            if "-" in _id:
                # Group
                if content["ZTEXT"] is not None:
                    # Chnaged name
                    try:
                        int(content["ZTEXT"])
                    except ValueError:
                        msg = f"The group name changed to {content['ZTEXT']}"
                        data[_id].messages[Z_PK].data = msg
                        data[_id].messages[Z_PK].meta = True
                    else:
                        del data[_id].messages[Z_PK]
                else:
                    data[_id].messages[Z_PK].data = None
            else:
                data[_id].messages[Z_PK].data = None
        else:
            # real message
            if content["ZMETADATA"] is not None and content["ZMETADATA"].startswith(b"\x2a\x14"):
                quoted = content["ZMETADATA"][2:19]
                data[_id].messages[Z_PK].reply = quoted.decode()
                data[_id].messages[Z_PK].quoted_data = None # TODO

            if content["ZISFROMME"] == 1:
                if content["ZMESSAGETYPE"] == 14:
                    msg = "Message deleted"
                    data[_id].messages[Z_PK].meta = True
                else:
                    msg = content["ZTEXT"]
                    if msg is not None:
                        if "\r\n" in msg:
                            msg = msg.replace("\r\n", "<br>")
                        if "\n" in msg:
                            msg = msg.replace("\n", "<br>")
            else:
                if content["ZMESSAGETYPE"] == 14:
                    msg = "Message deleted"
                    data[_id].messages[Z_PK].meta = True
                else:
                    msg = content["ZTEXT"]
                    if msg is not None:
                        if "\r\n" in msg:
                            msg = msg.replace("\r\n", "<br>")
                        if "\n" in msg:
                            msg = msg.replace("\n", "<br>")
            data[_id].messages[Z_PK].data = msg
        i += 1
        if i % 1000 == 0:
            print(f"Gathering messages...({i}/{total_row_number})", end="\r")
        content = c.fetchone()
    print(
        f"Gathering messages...({total_row_number}/{total_row_number})", end="\r")


def media(db, data, media_folder):
    c = db.cursor()
    # Get media
    c.execute("""SELECT count() FROM ZWAMEDIAITEM""")
    total_row_number = c.fetchone()[0]
    print(f"\nGathering media...(0/{total_row_number})", end="\r")
    i = 0
    c.execute("""SELECT COALESCE(ZWAMESSAGE.ZFROMJID, ZWAMESSAGE.ZTOJID) as _id,
                        ZMESSAGE,
                        ZMEDIALOCALPATH,
                        ZMEDIAURL,
                        ZVCARDSTRING,
                        ZMEDIAKEY,
                        ZTITLE
                 FROM ZWAMEDIAITEM
                    INNER JOIN ZWAMESSAGE
                        ON ZWAMEDIAITEM.ZMESSAGE = ZWAMESSAGE.Z_PK
                 WHERE ZMEDIALOCALPATH IS NOT NULL
                 ORDER BY _id ASC""")
    content = c.fetchone()
    mime = MimeTypes()
    while content is not None:
        file_path = f"{media_folder}/{content['ZMEDIALOCALPATH']}"
        _id = content["_id"]
        ZMESSAGE = content["ZMESSAGE"]
        data[_id].messages[ZMESSAGE].media = True

        if os.path.isfile(file_path):
            data[_id].messages[ZMESSAGE].data = file_path
            if content["ZVCARDSTRING"] is None:
                guess = mime.guess_type(file_path)[0]
                if guess is not None:
                    data[_id].messages[ZMESSAGE].mime = guess
                else:
                    data[_id].messages[ZMESSAGE].mime = "data/data"
            else:
                data[_id].messages[ZMESSAGE].mime = content["ZVCARDSTRING"]
        else:
            # if "https://mmg" in content["ZVCARDSTRING"]:
            # try:
            # r = requests.get(content["ZMEDIAURL"])
            # if r.status_code != 200:
            # raise RuntimeError()
            # except:
            # data[_id].messages[ZMESSAGE].data"] = "{The media is missing}"
            # data[_id].messages[ZMESSAGE].mime"] = "media"
            # else:
            data[_id].messages[ZMESSAGE].data = "The media is missing"
            data[_id].messages[ZMESSAGE].mime = "media"
            data[_id].messages[ZMESSAGE].meta = True
        if content["ZTITLE"] is not None:
            data[_id].messages[ZMESSAGE].caption = content["ZTITLE"]
        i += 1
        if i % 100 == 0:
            print(f"Gathering media...({i}/{total_row_number})", end="\r")
        content = c.fetchone()
    print(
        f"Gathering media...({total_row_number}/{total_row_number})", end="\r")


def vcard(db, data):
    c = db.cursor()
    c.execute("""SELECT DISTINCT ZWAVCARDMENTION.ZMEDIAITEM,
                        ZWAMEDIAITEM.ZMESSAGE,
                        COALESCE(ZWAMESSAGE.ZFROMJID,
                        ZWAMESSAGE.ZTOJID) as _id,
                        ZVCARDNAME,
                        ZVCARDSTRING
                 FROM ZWAVCARDMENTION
                    INNER JOIN ZWAMEDIAITEM
                        ON ZWAVCARDMENTION.ZMEDIAITEM = ZWAMEDIAITEM.Z_PK
                    INNER JOIN ZWAMESSAGE
                        ON ZWAMEDIAITEM.ZMESSAGE = ZWAMESSAGE.Z_PK""")
    contents = c.fetchall()
    total_row_number = len(contents)
    print(f"\nGathering vCards...(0/{total_row_number})", end="\r")
    base = "Message/vCards"
    if not os.path.isdir(base):
        Path(base).mkdir(parents=True, exist_ok=True)
    for index, content in enumerate(contents):
        file_name = "".join(x for x in content["ZVCARDNAME"] if x.isalnum())
        file_name = file_name.encode('utf-8')[:251].decode('utf-8', 'ignore')
        file_path = os.path.join(base, f"{file_name}.vcf")
        if not os.path.isfile(file_path):
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content["ZVCARDSTRING"])
        _id = content["_id"]
        ZMESSAGE = content["ZMESSAGE"]
        data[_id].messages[ZMESSAGE].data = content["ZVCARDNAME"] + \
            "The vCard file cannot be displayed here, " \
            f"however it should be located at {file_path}"
        data[_id].messages[ZMESSAGE].mime = "text/x-vcard"
        data[_id].messages[ZMESSAGE].media = True
        data[_id].messages[ZMESSAGE].meta = True
        print(f"Gathering vCards...({index + 1}/{total_row_number})", end="\r")


def create_html(data, output_folder, template=None, embedded=False, offline_static=False, maximum_size=None):
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

        safe_file_name = ''
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
        default="Message",
        help="Path to WhatsApp media folder"
    )
    # parser.add_option(
    #     "-t",
    #     "--template",
    #     dest="html",
    #     default="wa.db",
    #     help="Path to HTML template")
    (options, args) = parser.parse_args()
    msg_db = "7c7fba66680ef796b916b067077cc246adacf01d"
    output_folder = "temp"
    contact_db = options.wa
    media_folder = options.media

    if len(args) == 1:
        msg_db = args[0]
    elif len(args) == 2:
        msg_db = args[0]
        output_folder = args[1]

    data = {}

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
