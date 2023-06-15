#!/usr/bin/python3

from glob import glob
import sqlite3
import json
import jinja2
import os
import shutil
from pathlib import Path
from mimetypes import MimeTypes
from Whatsapp_Chat_Exporter.data_model import ChatStore, Message
from Whatsapp_Chat_Exporter.utility import MAX_SIZE, ROW_SIZE, rendering, sanitize_except, determine_day, APPLE_TIME, Device


def messages(db, data, media_folder):
    c = db.cursor()
    # Get contacts
    c.execute("""SELECT count() FROM ZWACHATSESSION""")
    total_row_number = c.fetchone()[0]
    print(f"Processing contacts...({total_row_number})")

    c.execute(
        """SELECT ZCONTACTJID,
                ZPARTNERNAME,
                ZPUSHNAME
           FROM ZWACHATSESSION
                LEFT JOIN ZWAPROFILEPUSHNAME
                    ON ZWACHATSESSION.ZCONTACTJID = ZWAPROFILEPUSHNAME.ZJID;"""
    )
    content = c.fetchone()
    while content is not None:
        is_phone = content["ZPARTNERNAME"].replace("+", "").replace(" ", "").isdigit()
        if content["ZPUSHNAME"] is None or (content["ZPUSHNAME"] and not is_phone):
            contact_name = content["ZPARTNERNAME"]
        else:
            contact_name = content["ZPUSHNAME"]
        data[content["ZCONTACTJID"]] = ChatStore(Device.IOS, contact_name, media_folder)
        path = f'{media_folder}/Media/Profile/{content["ZCONTACTJID"].split("@")[0]}'
        avatars = glob(f"{path}*")
        if 0 < len(avatars) <= 1:
            data[content["ZCONTACTJID"]].their_avatar = avatars[0]
        else:
            for avatar in avatars:
                if avatar.endswith(".thumb"):
                    data[content["ZCONTACTJID"]].their_avatar_thumb = avatar
                elif avatar.endswith(".jpg"):
                    data[content["ZCONTACTJID"]].their_avatar = avatar
        content = c.fetchone()

    # Get message history
    c.execute("""SELECT count() FROM ZWAMESSAGE""")
    total_row_number = c.fetchone()[0]
    print(f"Processing messages...(0/{total_row_number})", end="\r")

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
            data[_id] = ChatStore(Device.IOS)
            path = f'{media_folder}/Media/Profile/{_id.split("@")[0]}'
            avatars = glob(f"{path}*")
            if 0 < len(avatars) <= 1:
                data[_id].their_avatar = avatars[0]
            else:
                for avatar in avatars:
                    if avatar.endswith(".thumb"):
                        data[_id].their_avatar_thumb = avatar
                    elif avatar.endswith(".jpg"):
                        data[_id].their_avatar = avatar
        ts = APPLE_TIME + content["ZMESSAGEDATE"]
        message = Message(
            from_me=content["ZISFROMME"],
            timestamp=ts,
            time=ts, # TODO: Could be bug
            key_id=content["ZSTANZAID"][:17],
        )
        invalid = False
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
            message.sender = name or fallback
        else:
            message.sender = None
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
                        message.data = msg
                        message.meta = True
                    else:
                        invalid = True
                else:
                    message.data = None
            else:
                message.data = None
        else:
            # real message
            if content["ZMETADATA"] is not None and content["ZMETADATA"].startswith(b"\x2a\x14"):
                quoted = content["ZMETADATA"][2:19]
                message.reply = quoted.decode()
                message.quoted_data = None # TODO
            if content["ZMESSAGETYPE"] == 15: # Sticker
                message.sticker = True

            if content["ZISFROMME"] == 1:
                if content["ZMESSAGETYPE"] == 14:
                    msg = "Message deleted"
                    message.meta = True
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
                    message.meta = True
                else:
                    msg = content["ZTEXT"]
                    if msg is not None:
                        if "\r\n" in msg:
                            msg = msg.replace("\r\n", "<br>")
                        if "\n" in msg:
                            msg = msg.replace("\n", "<br>")
            message.data = msg
        if not invalid:
            data[_id].add_message(Z_PK, message)
        i += 1
        if i % 1000 == 0:
            print(f"Processing messages...({i}/{total_row_number})", end="\r")
        content = c.fetchone()
    print(
        f"Processing messages...({total_row_number}/{total_row_number})", end="\r")


def media(db, data, media_folder):
    c = db.cursor()
    # Get media
    c.execute("""SELECT count() FROM ZWAMEDIAITEM""")
    total_row_number = c.fetchone()[0]
    print(f"\nProcessing media...(0/{total_row_number})", end="\r")
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
        file_path = f"{media_folder}/Message/{content['ZMEDIALOCALPATH']}"
        _id = content["_id"]
        ZMESSAGE = content["ZMESSAGE"]
        message = data[_id].messages[ZMESSAGE]
        message.media = True
        if os.path.isfile(file_path):
            message.data = file_path
            if content["ZVCARDSTRING"] is None:
                guess = mime.guess_type(file_path)[0]
                if guess is not None:
                    message.mime = guess
                else:
                    message.mime = "application/octet-stream"
            else:
                message.mime = content["ZVCARDSTRING"]
        else:
            if False: # Block execution
                try:
                    r = requests.get(content["ZMEDIAURL"])
                    if r.status_code != 200:
                        raise RuntimeError()
                except:
                    message.data = "The media is missing"
                    message.mime = "media"
                    message.meta = True
                else:
                    ...
            message.data = "The media is missing"
            message.mime = "media"
            message.meta = True
        if content["ZTITLE"] is not None:
            message.caption = content["ZTITLE"]
        i += 1
        if i % 100 == 0:
            print(f"Processing media...({i}/{total_row_number})", end="\r")
        content = c.fetchone()
    print(
        f"Processing media...({total_row_number}/{total_row_number})", end="\r")


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
    print(f"\nProcessing vCards...(0/{total_row_number})", end="\r")
    base = "AppDomainGroup-group.net.whatsapp.WhatsApp.shared/Message/vCards"
    if not os.path.isdir(base):
        Path(base).mkdir(parents=True, exist_ok=True)
    for index, content in enumerate(contents):
        file_name = "".join(x for x in content["ZVCARDNAME"] if x.isalnum())
        file_name = file_name.encode('utf-8')[:251].decode('utf-8', 'ignore')
        file_path = os.path.join(base, f"{file_name}.vcf")
        if not os.path.isfile(file_path):
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content["ZVCARDSTRING"])
        message = data[content["_id"]].messages[content["ZMESSAGE"]]
        message.data = content["ZVCARDNAME"] + \
            "The vCard file cannot be displayed here, " \
            f"however it should be located at {file_path}"
        message.mime = "text/x-vcard"
        message.media = True
        message.meta = True
        print(f"Processing vCards...({index + 1}/{total_row_number})", end="\r")


def create_html(
        data,
        output_folder,
        template=None,
        embedded=False,
        offline_static=False,
        maximum_size=None,
        no_avatar=False
    ):
    if template is None:
        template_dir = os.path.dirname(__file__)
        template_file = "whatsapp.html"
    else:
        template_dir = os.path.dirname(template)
        template_file = os.path.basename(template)
    template_loader = jinja2.FileSystemLoader(searchpath=template_dir)
    template_env = jinja2.Environment(loader=template_loader, autoescape=True)
    template_env.globals.update(
        determine_day=determine_day,
        no_avatar=no_avatar
    )
    template_env.filters['sanitize_except'] = sanitize_except
    template = template_env.get_template(template_file)

    total_row_number = len(data)
    print(f"\nGenerating chats...(0/{total_row_number})", end="\r")

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
                    current_size += ROW_SIZE + 100 # Assume media and meta HTML are 100 bytes
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
                        chat.my_avatar,
                        chat.their_avatar,
                        chat.their_avatar_thumb
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
                            False,
                            chat.my_avatar,
                            chat.their_avatar,
                            chat.their_avatar_thumb
                        )
                    else:
                        render_box.append(message)
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
                chat.my_avatar,
                chat.their_avatar,
                chat.their_avatar_thumb
            )
        if current % 10 == 0:
            print(f"Generating chats...({current}/{total_row_number})", end="\r")

    print(f"Generating chats...({total_row_number}/{total_row_number})", end="\r")


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
