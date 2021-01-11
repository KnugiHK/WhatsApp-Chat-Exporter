#!/usr/bin/python3

import sqlite3
import sys
import json
import jinja2
import os
import base64
from datetime import datetime

def determine_day(last, current):
    last = datetime.fromtimestamp(last).date()
    current = datetime.fromtimestamp(current).date()
    #print(last, current)
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
while content is not None:
    file_path = f"WhatsApp/{content[2]}"
    if os.path.isfile(file_path):
        with open(file_path, "rb") as f:
            data[content[0]]["messages"][content[1]]["data"] = base64.b64encode(f.read()).decode("utf-8")
            data[content[0]]["messages"][content[1]]["media"] = True
    data[content[0]]["messages"][content[1]]["mime"] = content[4]
    i += 1
    if i % 1000 == 0:
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
    
    with open(f"temp/{file_name}.html", "w", encoding="utf-8") as f:
        f.write(template.render(name=data[i]["name"] if data[i]["name"] is not None else phone_number, msgs=data[i]["messages"].values()))
    if current % 10 == 0:
        print(f"Creating HTML...({current}/{total_row_number})", end="\r")
print(f"Creating HTML...({total_row_number}/{total_row_number})", end="\r")

with open("result.json", "w") as f:
    data = json.dumps(data)
    print(f"\nWriting JSON file...({int(len(data)/1024/1024)}MB)")
    f.write(data)

print("Everything is done!")
