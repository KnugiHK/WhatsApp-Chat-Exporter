#!/usr/bin/python3

import os
import shutil
from glob import glob
from pathlib import Path
from mimetypes import MimeTypes
from markupsafe import escape as htmle
from Whatsapp_Chat_Exporter.data_model import ChatStore, Message
from Whatsapp_Chat_Exporter.utility import APPLE_TIME, Device, get_chat_condition, slugify


def contacts(db, data):
    c = db.cursor()
    # Get status only lol
    c.execute("""SELECT count() FROM ZWAADDRESSBOOKCONTACT WHERE ZABOUTTEXT IS NOT NULL""")
    total_row_number = c.fetchone()[0]
    print(f"Pre-processing contacts...({total_row_number})")
    c.execute("""SELECT ZWHATSAPPID, ZABOUTTEXT FROM ZWAADDRESSBOOKCONTACT WHERE ZABOUTTEXT IS NOT NULL""")
    content = c.fetchone()
    while content is not None:
        if not content["ZWHATSAPPID"].endswith("@s.whatsapp.net"):
            ZWHATSAPPID = content["ZWHATSAPPID"] + "@s.whatsapp.net"
        data[ZWHATSAPPID] = ChatStore(Device.IOS)
        data[ZWHATSAPPID].status = content["ZABOUTTEXT"]
        content = c.fetchone()


def messages(db, data, media_folder, timezone_offset, filter_date, filter_chat):
    c = db.cursor()
    # Get contacts
    c.execute(
        f"""SELECT count() 
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
                {get_chat_condition(filter_chat[0], True, ["ZWACHATSESSION.ZCONTACTJID", "ZMEMBERJID"], "ZGROUPINFO", "ios")}
                {get_chat_condition(filter_chat[1], False, ["ZWACHATSESSION.ZCONTACTJID", "ZMEMBERJID"], "ZGROUPINFO", "ios")}
            GROUP BY ZCONTACTJID);"""
    )
    total_row_number = c.fetchone()[0]
    print(f"Processing contacts...({total_row_number})")

    c.execute(
        f"""SELECT DISTINCT ZCONTACTJID,
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
                {get_chat_condition(filter_chat[0], True, ["ZWACHATSESSION.ZCONTACTJID", "ZMEMBERJID"], "ZGROUPINFO", "ios")}
                {get_chat_condition(filter_chat[1], False, ["ZWACHATSESSION.ZCONTACTJID", "ZMEMBERJID"], "ZGROUPINFO", "ios")}
            GROUP BY ZCONTACTJID;"""
    )
    content = c.fetchone()
    while content is not None:
        is_phone = content["ZPARTNERNAME"].replace("+", "").replace(" ", "").isdigit()
        if content["ZPUSHNAME"] is None or (content["ZPUSHNAME"] and not is_phone):
            contact_name = content["ZPARTNERNAME"]
        else:
            contact_name = content["ZPUSHNAME"]
        contact_id = content["ZCONTACTJID"]
        if contact_id not in data:
            data[contact_id] = ChatStore(Device.IOS, contact_name, media_folder)
        else:
            data[contact_id].name = contact_name
            data[contact_id].my_avatar = os.path.join(media_folder, "Media/Profile/Photo.jpg")
        path = f'{media_folder}/Media/Profile/{contact_id.split("@")[0]}'
        avatars = glob(f"{path}*")
        if 0 < len(avatars) <= 1:
            data[contact_id].their_avatar = avatars[0]
        else:
            for avatar in avatars:
                if avatar.endswith(".thumb") and data[content["ZCONTACTJID"]].their_avatar_thumb is None:
                    data[contact_id].their_avatar_thumb = avatar
                elif avatar.endswith(".jpg") and data[content["ZCONTACTJID"]].their_avatar is None:
                    data[contact_id].their_avatar = avatar
        content = c.fetchone()

    # Get message history
    c.execute(f"""SELECT count()
                  FROM ZWAMESSAGE
                        INNER JOIN ZWACHATSESSION
                            ON ZWAMESSAGE.ZCHATSESSION = ZWACHATSESSION.Z_PK
                        LEFT JOIN ZWAGROUPMEMBER
                            ON ZWAMESSAGE.ZGROUPMEMBER = ZWAGROUPMEMBER.Z_PK
                  WHERE 1=1
                    {f'AND ZMESSAGEDATE {filter_date}' if filter_date is not None else ''}
                    {get_chat_condition(filter_chat[0], True, ["ZWACHATSESSION.ZCONTACTJID", "ZMEMBERJID"], "ZGROUPINFO", "ios")}
                    {get_chat_condition(filter_chat[1], False, ["ZWACHATSESSION.ZCONTACTJID", "ZMEMBERJID"], "ZGROUPINFO", "ios")}""")
    total_row_number = c.fetchone()[0]
    print(f"Processing messages...(0/{total_row_number})", end="\r")
    c.execute(f"""SELECT ZCONTACTJID,
                        ZWAMESSAGE.Z_PK,
                        ZISFROMME,
                        ZMESSAGEDATE,
                        ZTEXT,
                        ZMESSAGETYPE,
                        ZWAGROUPMEMBER.ZMEMBERJID,
						ZMETADATA,
                        ZSTANZAID,
                        ZGROUPINFO
                 FROM ZWAMESSAGE
                    LEFT JOIN ZWAGROUPMEMBER
                        ON ZWAMESSAGE.ZGROUPMEMBER = ZWAGROUPMEMBER.Z_PK
					LEFT JOIN ZWAMEDIAITEM
						ON ZWAMESSAGE.Z_PK = ZWAMEDIAITEM.ZMESSAGE
                    INNER JOIN ZWACHATSESSION
                        ON ZWAMESSAGE.ZCHATSESSION = ZWACHATSESSION.Z_PK
                 WHERE 1=1   
                    {f'AND ZMESSAGEDATE {filter_date}' if filter_date is not None else ''}
                    {get_chat_condition(filter_chat[0], True, ["ZCONTACTJID", "ZMEMBERJID"], "ZGROUPINFO", "ios")}
                    {get_chat_condition(filter_chat[1], False, ["ZCONTACTJID", "ZMEMBERJID"], "ZGROUPINFO", "ios")}
                 ORDER BY ZMESSAGEDATE ASC;""")
    i = 0
    content = c.fetchone()
    while content is not None:
        ZCONTACTJID = content["ZCONTACTJID"]
        Z_PK = content["Z_PK"]
        is_group_message = content["ZGROUPINFO"] is not None
        if ZCONTACTJID not in data:
            data[ZCONTACTJID] = ChatStore(Device.IOS)
            path = f'{media_folder}/Media/Profile/{ZCONTACTJID.split("@")[0]}'
            avatars = glob(f"{path}*")
            if 0 < len(avatars) <= 1:
                data[ZCONTACTJID].their_avatar = avatars[0]
            else:
                for avatar in avatars:
                    if avatar.endswith(".thumb"):
                        data[ZCONTACTJID].their_avatar_thumb = avatar
                    elif avatar.endswith(".jpg"):
                        data[ZCONTACTJID].their_avatar = avatar
        ts = APPLE_TIME + content["ZMESSAGEDATE"]
        message = Message(
            from_me=content["ZISFROMME"],
            timestamp=ts,
            time=ts, # TODO: Could be bug
            key_id=content["ZSTANZAID"][:17],
            timezone_offset=timezone_offset
        )
        invalid = False
        if is_group_message and content["ZISFROMME"] == 0:
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
            if is_group_message:
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
            data[ZCONTACTJID].add_message(Z_PK, message)
        i += 1
        if i % 1000 == 0:
            print(f"Processing messages...({i}/{total_row_number})", end="\r")
        content = c.fetchone()
    print(
        f"Processing messages...({total_row_number}/{total_row_number})", end="\r")


def media(db, data, media_folder, filter_date, filter_chat, separate_media=False):
    c = db.cursor()
    # Get media
    c.execute(f"""SELECT count()
                  FROM ZWAMEDIAITEM
                    INNER JOIN ZWAMESSAGE
                        ON ZWAMEDIAITEM.ZMESSAGE = ZWAMESSAGE.Z_PK
                    INNER JOIN ZWACHATSESSION
                        ON ZWAMESSAGE.ZCHATSESSION = ZWACHATSESSION.Z_PK
                    LEFT JOIN ZWAGROUPMEMBER
                        ON ZWAMESSAGE.ZGROUPMEMBER = ZWAGROUPMEMBER.Z_PK
                  WHERE 1=1
                    {f'AND ZMESSAGEDATE {filter_date}' if filter_date is not None else ''}
                    {get_chat_condition(filter_chat[0], True, ["ZWACHATSESSION.ZCONTACTJID","ZMEMBERJID"], "ZGROUPINFO", "ios")}
                    {get_chat_condition(filter_chat[1], False, ["ZWACHATSESSION.ZCONTACTJID", "ZMEMBERJID"], "ZGROUPINFO", "ios")}
                """)
    total_row_number = c.fetchone()[0]
    print(f"\nProcessing media...(0/{total_row_number})", end="\r")
    i = 0
    c.execute(f"""SELECT ZCONTACTJID,
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
                    {f'AND ZWAMESSAGE.ZMESSAGEDATE {filter_date}' if filter_date is not None else ''}
                    {get_chat_condition(filter_chat[0], True, ["ZCONTACTJID", "ZMEMBERJID"], "ZGROUPINFO", "ios")}
                    {get_chat_condition(filter_chat[1], False, ["ZCONTACTJID", "ZMEMBERJID"], "ZGROUPINFO", "ios")}
                 ORDER BY ZCONTACTJID ASC""")
    content = c.fetchone()
    mime = MimeTypes()
    while content is not None:
        file_path = f"{media_folder}/Message/{content['ZMEDIALOCALPATH']}"
        ZMESSAGE = content["ZMESSAGE"]
        contact = data[content["ZCONTACTJID"]]
        message = contact.messages[ZMESSAGE]
        message.media = True
        if contact.media_base == "":
            contact.media_base = media_folder + "/"
        if os.path.isfile(file_path):
            message.data = '/'.join(file_path.split("/")[1:])
            if content["ZVCARDSTRING"] is None:
                guess = mime.guess_type(file_path)[0]
                if guess is not None:
                    message.mime = guess
                else:
                    message.mime = "application/octet-stream"
            else:
                message.mime = content["ZVCARDSTRING"]
            if separate_media:
                chat_display_name = slugify(contact.name or message.sender \
                                            or content["ZCONTACTJID"].split('@')[0], True)
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
        if content["ZTITLE"] is not None:
            message.caption = content["ZTITLE"]
        i += 1
        if i % 100 == 0:
            print(f"Processing media...({i}/{total_row_number})", end="\r")
        content = c.fetchone()
    print(
        f"Processing media...({total_row_number}/{total_row_number})", end="\r")


def vcard(db, data, media_folder, filter_date, filter_chat):
    c = db.cursor()
    c.execute(f"""SELECT DISTINCT ZWAVCARDMENTION.ZMEDIAITEM,
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
                    {f'AND ZWAMESSAGE.ZMESSAGEDATE {filter_date}' if filter_date is not None else ''}
                    {get_chat_condition(filter_chat[0], True, ["ZCONTACTJID", "ZMEMBERJID"], "ZGROUPINFO", "ios")}
                    {get_chat_condition(filter_chat[1], False, ["ZCONTACTJID", "ZMEMBERJID"], "ZGROUPINFO", "ios")};""")
    contents = c.fetchall()
    total_row_number = len(contents)
    print(f"\nProcessing vCards...(0/{total_row_number})", end="\r")
    path = f'{media_folder}/Message/vCards'
    Path(path).mkdir(parents=True, exist_ok=True)

    for index, content in enumerate(contents):
        file_paths = []
        vcard_names = content["ZVCARDNAME"].split("_$!<Name-Separator>!$_")
        vcard_strings = content["ZVCARDSTRING"].split("_$!<VCard-Separator>!$_")

        # If this is a list of contacts
        if len(vcard_names) > len(vcard_strings):
            vcard_names.pop(0)  # Dismiss the first element, which is the group name

        for name, vcard_string in zip(vcard_names, vcard_strings):
            file_name = "".join(x for x in name if x.isalnum())
            file_name = file_name.encode('utf-8')[:230].decode('utf-8', 'ignore')
            file_path = os.path.join(path, f"{file_name}.vcf")
            file_paths.append(file_path)

            if not os.path.isfile(file_path):
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(vcard_string)

        vcard_summary = "This media include the following vCard file(s):<br>" 
        vcard_summary += " | ".join([f'<a href="{htmle(fp)}">{htmle(name)}</a>' for name, fp in zip(vcard_names, file_paths)])
        message = data[content["ZCONTACTJID"]].messages[content["ZMESSAGE"]]
        message.data = vcard_summary
        message.mime = "text/x-vcard"
        message.media = True
        message.meta = True
        message.safe = True
        print(f"Processing vCards...({index + 1}/{total_row_number})", end="\r")
