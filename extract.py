#!/usr/bin/python3

import sqlite3
import sys
import json
import jinja2
import os
import base64
import requests
import shutil
from datetime import datetime
from mimetypes import MimeTypes


def determine_day(last, current):
    last = datetime.fromtimestamp(last).date()
    current = datetime.fromtimestamp(current).date()
    if last == current:
        return None
    else:
        return current

data = {}

# Get contacts
wa = sqlite3.connect("wa.db")
c = wa.cursor()
c.execute("""SELECT count() FROM wa_contacts""")
total_row_number = c.fetchone()[0]
print(f"Gathering contacts...({total_row_number})")

c.execute("""SELECT jid, display_name FROM wa_contacts; """)
row = c.fetchone()
while row is not None:
    data[row[0]] = {"name": row[1], "messages":{}}
    row = c.fetchone()
wa.close()

# Get message history
msg = sqlite3.connect("msgstore.db")
c = msg.cursor()
c.execute("""SELECT count() FROM messages""")
total_row_number = c.fetchone()[0]
print(f"Gathering messages...(0/{total_row_number})", end="\r")

c.execute("""SELECT key_remote_jid, _id, key_from_me, timestamp, data FROM messages; """)
i = 0
content = c.fetchone()
while content is not None:
    if content[0] not in data:
        data[content[0]] = {"name": None, "messages": {}}
    data[content[0]]["messages"][content[1]] = {
        "from_me": bool(content[2]),
        "timestamp": content[3]/1000,
        "time": datetime.fromtimestamp(content[3]/1000).strftime("%H:%M"),
        "data": content[4],
        "media": False
    }
    i += 1
    if i % 1000 == 0:
        print(f"Gathering messages...({i}/{total_row_number})", end="\r")
    content = c.fetchone()
print(f"Gathering messages...({total_row_number}/{total_row_number})", end="\r")
# Get media

c.execute("""SELECT count() FROM message_media""")
total_row_number = c.fetchone()[0]
print(f"\nGathering media...(0/{total_row_number})", end="\r")
i = 0
c.execute("""SELECT messages.key_remote_jid, message_row_id, file_path, message_url, mime_type, media_key FROM message_media INNER JOIN messages ON message_media.message_row_id = messages._id ORDER BY messages.key_remote_jid ASC""")
content = c.fetchone()
mime = MimeTypes()
while content is not None:
    file_path = f"WhatsApp/{content[2]}"
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
print(f"Gathering media...({total_row_number}/{total_row_number})", end="\r")

templateLoader = jinja2.FileSystemLoader(searchpath="./")
templateEnv = jinja2.Environment(loader=templateLoader)
templateEnv.globals.update(determine_day=determine_day)
TEMPLATE_FILE = "whatsapp.html"
template = templateEnv.get_template(TEMPLATE_FILE)

total_row_number = len(data)
print(f"\nCreating HTML...(0/{total_row_number})", end="\r")

if len(sys.argv) < 3:
    output_folder = "temp"    
else:
    output_folder = sys.argv[2]

if not os.path.isdir(output_folder):
    os.mkdir(output_folder)

for current, i in enumerate(data):
    if len(data[i]["messages"]) == 0:
        continue
    phone_number = i.split('@')[0]
    if "-"in i:
        file_name = ""
    else:
        file_name = phone_number
    
    if data[i]["name"] is not None:
        if file_name != "":
            file_name += "-"
        file_name += data[i]["name"].replace("/", "-")
        name = data[i]["name"]
    else:
        name = phone_number

    with open(f"{output_folder}/{file_name}.html", "w", encoding="utf-8") as f:
        f.write(template.render(name=name, msgs=data[i]["messages"].values(), my_avatar=None, their_avatar=f"WhatsApp/Avatars/{i}.j"))
    if current % 10 == 0:
        print(f"Creating HTML...({current}/{total_row_number})", end="\r")
    
print(f"Creating HTML...({total_row_number}/{total_row_number})", end="\r")

if not os.path.isdir(f"{output_folder}/WhatsApp"):
    shutil.move("WhatsApp", f"{output_folder}/")

with open("result.json", "w") as f:
    data = json.dumps(data)
    print(f"\nWriting JSON file...({int(len(data)/1024/1024)}MB)")
    f.write(data)

print("Everything is done!")
