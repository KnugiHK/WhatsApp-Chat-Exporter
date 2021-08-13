#!/usr/bin/python3

import sqlite3
import json
import jinja2
import os
import requests
import shutil
import pkgutil
from pathlib import Path
from bleach import clean as sanitize
from markupsafe import Markup
from datetime import datetime
from mimetypes import MimeTypes

APPLE_TIME = datetime.timestamp(datetime(2001, 1, 1))


def sanitize_except(html):
    return Markup(sanitize(html, tags=["br"]))


def determine_day(last, current):
    last = datetime.fromtimestamp(last).date()
    current = datetime.fromtimestamp(current).date()
    if last == current:
        return None
    else:
        return current


def messages(db, data):
    c = db.cursor()
    # Get contacts
    c.execute("""SELECT count() FROM ZWACHATSESSION""")
    total_row_number = c.fetchone()[0]
    print(f"Gathering contacts...({total_row_number})")

    c.execute("""SELECT ZCONTACTJID, ZPARTNERNAME FROM ZWACHATSESSION; """)
    row = c.fetchone()
    while row is not None:
        data[row[0]] = {"name": row[1], "messages": {}}
        row = c.fetchone()

    # Get message history
    c.execute("""SELECT count() FROM ZWAMESSAGE""")
    total_row_number = c.fetchone()[0]
    print(f"Gathering messages...(0/{total_row_number})", end="\r")

    c.execute("""SELECT COALESCE(ZFROMJID, ZTOJID),
                        ZWAMESSAGE.Z_PK,
                        ZISFROMME,
                        ZMESSAGEDATE,
                        ZTEXT,
                        ZMESSAGETYPE,
                        ZWAGROUPMEMBER.ZMEMBERJID
                 FROM main.ZWAMESSAGE
                    LEFT JOIN main.ZWAGROUPMEMBER
                        ON main.ZWAMESSAGE.ZGROUPMEMBER = main.ZWAGROUPMEMBER.Z_PK;""")
    i = 0
    content = c.fetchone()
    while content is not None:
        if content[0] not in data:
            data[content[0]] = {"name": None, "messages": {}}
        ts = APPLE_TIME + content[3]
        data[content[0]]["messages"][content[1]] = {
            "from_me": bool(content[2]),
            "timestamp": ts,
            "time": datetime.fromtimestamp(ts).strftime("%H:%M"),
            "media": False,
            "reply": None,
            "caption": None,
            "meta": False,
            "data": None
        }
        if "-" in content[0] and content[2] == 0:
            name = None
            if content[6] is not None:
                if content[6] in data:
                    name = data[content[6]]["name"]
                if "@" in content[6]:
                    fallback = content[6].split('@')[0]
                else:
                    fallback = None
            else:
                fallback = None
            data[content[0]]["messages"][content[1]]["sender"] = name or fallback
        else:
            data[content[0]]["messages"][content[1]]["sender"] = None
        if content[5] == 6:
            # Metadata
            if "-" in content[0]:
                # Group
                if content[4] is not None:
                    # Chnaged name
                    try:
                        int(content[4])
                    except ValueError:
                        msg = f"The group name changed to {content[4]}"
                        data[content[0]]["messages"][content[1]]["data"] = msg
                        data[content[0]]["messages"][content[1]]["meta"] = True
                    else:
                        del data[content[0]]["messages"][content[1]]
                else:
                    data[content[0]]["messages"][content[1]]["data"] = None
            else:
                data[content[0]]["messages"][content[1]]["data"] = None
        else:
            # real message
            if content[2] == 1:
                if content[5] == 14:
                    msg = "Message deleted"
                    data[content[0]]["messages"][content[1]]["meta"] = True
                else:
                    msg = content[4]
                    if msg is not None:
                        if "\r\n" in msg:
                            msg = msg.replace("\r\n", "<br>")
                        if "\n" in msg:
                            msg = msg.replace("\n", "<br>")
            else:
                if content[5] == 14:
                    msg = "Message deleted"
                    data[content[0]]["messages"][content[1]]["meta"] = True
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
            # data[content[0]]["messages"][content[1]]["mime"] = "media"
            # else:
            data[content[0]]["messages"][content[1]]["data"] = "The media is missing"
            data[content[0]]["messages"][content[1]]["mime"] = "media"
            data[content[0]]["messages"][content[1]]["meta"] = True
        if content[6] is not None:
            data[content[0]]["messages"][content[1]]["caption"] = content[6]
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
    rows = c.fetchall()
    total_row_number = len(rows)
    print(f"\nGathering vCards...(0/{total_row_number})", end="\r")
    base = "Message/vCards"
    if not os.path.isdir(base):
        Path(base).mkdir(parents=True, exist_ok=True)
    for index, row in enumerate(rows):
        file_name = "".join(x for x in row[3] if x.isalnum())
        file_path = f"{base}/{file_name[:200]}.vcf"
        if not os.path.isfile(file_path):
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(row[4])
        data[row[2]]["messages"][row[1]]["data"] = row[3] + \
            "The vCard file cannot be displayed here, " \
            f"however it should be located at {file_path}"
        data[row[2]]["messages"][row[1]]["mime"] = "text/x-vcard"
        data[row[2]]["messages"][row[1]]["media"] = True
        data[row[2]]["messages"][row[1]]["meta"] = True
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
