#!/usr/bin/python3

import sqlite3
import sys
import json
import jinja2
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
wa = sqlite3.connect("wa.db")

c = wa.cursor()
c.execute("""SELECT jid, display_name FROM "main"."wa_contacts"; """)
row = c.fetchone()
while row is not None:
    data[row[0]] = {"name": row[1], "messages":{}}
    row = c.fetchone()

msg = sqlite3.connect("msgstore.db")
c = msg.cursor()

c.execute("""SELECT key_remote_jid, _id, key_from_me, timestamp, data FROM "main"."messages"; """)
content = c.fetchone()
while content is not None:
    if content[0] not in data:
        data[content[0]] = {"name": None, "messages": {}}
    data[content[0]]["messages"][content[1]] = {
        "from_me": bool(content[2]),
        "timestamp": content[3]/1000,
        "time": datetime.fromtimestamp(content[3]/1000).strftime("%H:%M"),
        "data": content[4]
    }
    content = c.fetchone()

templateLoader = jinja2.FileSystemLoader(searchpath="./")
templateEnv = jinja2.Environment(loader=templateLoader)
templateEnv.globals.update(determine_day=determine_day)
TEMPLATE_FILE = "whatsapp.html"
template = templateEnv.get_template(TEMPLATE_FILE)

for i in data:
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

with open("result.json", "w") as f:
    f.write(json.dumps(data))