#!/usr/bin/python3

import sqlite3
import sys
import json
import jinja2
import os
import base64
import requests
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
msg = sqlite3.connect("7c7fba66680ef796b916b067077cc246adacf01d")
c = msg.cursor()
c.execute("""SELECT count() FROM ZWACHATSESSION""")
total_row_number = c.fetchone()[0]
print(f"Gathering contacts...({total_row_number})")

c.execute("""SELECT ZCONTACTJID, ZPARTNERNAME FROM ZWACHATSESSION; """)
row = c.fetchone()
while row is not None:
    data[row[0]] = {"name": row[1], "messages":{}}
    row = c.fetchone()

# Get message history
c.execute("""SELECT count() FROM ZWAMESSAGE""")
total_row_number = c.fetchone()[0]
apple_time = datetime.timestamp(datetime(2001,1,1))
print(f"Gathering messages...(0/{total_row_number})", end="\r")

c.execute("""SELECT COALESCE(ZFROMJID, ZTOJID), Z_PK, ZISFROMME, ZMESSAGEDATE, ZTEXT FROM ZWAMESSAGE;""")
i = 0
content = c.fetchone()
while content is not None:
    if content[0] not in data:
        data[content[0]] = {"name": None, "messages": {}}
    ts = apple_time + content[3]
    data[content[0]]["messages"][content[1]] = {
        "from_me": bool(content[2]),
        "timestamp": ts,
        "time": datetime.fromtimestamp(ts).strftime("%H:%M"),
        "data": content[4],
        "media": False
    }
    i += 1
    if i % 1000 == 0:
        print(f"Gathering messages...({i}/{total_row_number})", end="\r")
    content = c.fetchone()
print(f"Gathering messages...({total_row_number}/{total_row_number})", end="\r")

templateLoader = jinja2.FileSystemLoader(searchpath="./")
templateEnv = jinja2.Environment(loader=templateLoader)
templateEnv.globals.update(determine_day=determine_day)
TEMPLATE_FILE = "whatsapp.html"
template = templateEnv.get_template(TEMPLATE_FILE)

total_row_number_html = len(data)
print(f"\nCreating HTML...(0/{total_row_number})", end="\r")

if len(sys.argv) < 3:
    output_folder = "temp"    
else:
    output_folder = sys.argv[2]

if not os.path.isdir(output_folder):
    os.mkdir(output_folder)

list_of_contact = tuple(data.keys())

for current, contact in enumerate(list_of_contact):
    if len(data[contact]["messages"]) == 0:
        continue
    # Get media
    c.execute("""SELECT count() FROM ZWAMEDIAITEM INNER JOIN ZWAMESSAGE ON ZWAMEDIAITEM.ZMESSAGE = ZWAMESSAGE.Z_PK WHERE ZMEDIALOCALPATH IS NOT NULL AND COALESCE(ZWAMESSAGE.ZFROMJID, ZWAMESSAGE.ZTOJID)=?""", [contact])
    total_row_number = c.fetchone()[0]
    phone_number = contact.split('@')[0]
    print(f"Creating HTML...({current}/{total_row_number_html})|Gathering media with {phone_number}...(0/{total_row_number})", end="\r")
    j = 0
    c.execute("""SELECT COALESCE(ZWAMESSAGE.ZFROMJID, ZWAMESSAGE.ZTOJID) as jid, ZMESSAGE, ZMEDIALOCALPATH, ZMEDIAURL, ZVCARDSTRING, ZMEDIAKEY FROM ZWAMEDIAITEM INNER JOIN ZWAMESSAGE ON ZWAMEDIAITEM.ZMESSAGE = ZWAMESSAGE.Z_PK WHERE ZMEDIALOCALPATH IS NOT NULL AND jid=? ORDER BY jid ASC""", [contact])
    contents = c.fetchall()
    mime = MimeTypes()
    for content in contents:
        file_path = f"Message/{content[2]}"
        data[content[0]]["messages"][content[1]]["media"] = True
        if os.path.isfile(file_path):
            with open(file_path, "rb") as f:
                data[content[0]]["messages"][content[1]]["data"] = base64.b64encode(f.read()).decode("utf-8")
            if content[4] is None:
                guess = mime.guess_type(file_path)[0]
                if guess is not None:
                    data[content[0]]["messages"][content[1]]["mime"] = guess
                else:
                    data[content[0]]["messages"][content[1]]["mime"] = "image/jpeg"
            else:
                data[content[0]]["messages"][content[1]]["mime"] = content[4]
        else:
            # if "https://mmg" in content[2]:
                # try:
                    # r = requests.get(content[2])
                    # if r.status_code != 200:
                        # raise RuntimeError()
                # except:
                    # data[contact]["messages"][content[0]]["data"] = "{The media is missing}"
                    # data[contact]["messages"][content[0]]["media"] = True
                    # data[contact]["messages"][content[0]]["mime"] = "media"
                # else:
                    # open('temp.file', 'wb').write(r.content)
                    # open('temp.asdasda', "a").write(content[3])
            # else:
            data[content[0]]["messages"][content[1]]["data"] = "{The media is missing}"
            data[content[0]]["messages"][content[1]]["mime"] = "media"
        j += 1
        if j % 100 == 0:
            print(f"Creating HTML...({current}/{total_row_number_html})|Gathering media with {phone_number}...({j}/{total_row_number})                ", end="\r")
    print(f"Creating HTML...({current}/{total_row_number_html})|Gathering media with {phone_number}...({total_row_number}/{total_row_number})           ", end="\r")
    if "-" in contact:
        file_name = ""
    else:
        file_name = phone_number
    
    if data[contact]["name"] is not None:
        if file_name != "":
            file_name += "-"
        file_name += data[contact]["name"].replace("/", "-")
    if data[contact]["name"]:
        name = data[contact]["name"]
    else:
        name = phone_number

    with open(f"{output_folder}/{file_name}.html", "w", encoding="utf-8") as f:
        f.write(template.render(name=name, msgs=data[contact]["messages"].values()))
    
    del data[contact]
    #if current % 10 == 0:
    #print(f"Creating HTML...({current}/{total_row_number})", end="\r")
    
print(f"Creating HTML...({total_row_number_html}/{total_row_number_html})                                                       ")
print("Everything is done!                                                                        ")
