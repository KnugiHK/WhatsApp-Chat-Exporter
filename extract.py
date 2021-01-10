#!/usr/bin/python3

import sqlite3
import sys
import json
import jinja2

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

c.execute("""SELECT key_remote_jid, _id, key_from_me, data FROM "main"."messages"; """)
content = c.fetchone()
while content is not None:
    if content[0] not in data:
        data[content[0]] = {"name": None, "messages": {}}
    data[content[0]]["messages"][content[1]] = {"from_me": bool(content[2]), "data": content[3]}
    content = c.fetchone()

templateLoader = jinja2.FileSystemLoader(searchpath="./")
templateEnv = jinja2.Environment(loader=templateLoader)
TEMPLATE_FILE = "whatsapp.html"
template = templateEnv.get_template(TEMPLATE_FILE)

for i in data:
    with open(f"temp/{i.split('@')[0]}.html", "w", encoding="utf-8") as f:
        f.write(template.render(name=data[i]["name"], msgs=data[i]["messages"].values()))

with open("result.json", "w") as f:
    f.write(json.dumps(data))