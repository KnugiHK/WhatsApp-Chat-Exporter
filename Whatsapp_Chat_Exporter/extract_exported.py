from datetime import datetime
from mimetypes import MimeTypes
import os
from Whatsapp_Chat_Exporter.data_model import ChatStore, Message


def messages(path, data, assume_first_as_me=False):
    """Extracts messages from the exported file"""
    with open(path, "r", encoding="utf8") as file:
        you = ""
        data["chat"] = ChatStore()
        total_row_number = len(file.readlines())
        i = 0
        file.seek(0)
        for index, line in enumerate(file):
            if len(line.split(" - ")) > 1:
                time = line.split(" - ")[0]
                if ":" not in line.split(time)[1]:
                    msg.data = line.split(time)[1][3:]
                    msg.meta = True
                else:
                    name = line.split(time)[1].split(":")[0]
                    message = line.split(time)[1].split(name + ":")[1].strip()
                    name = name[3:]
                    if you == "":
                        if data["chat"].name is None:
                            if not assume_first_as_me:
                                while True:
                                    ans = input(f"Is '{name}' you? (Y/N)").lower()
                                    if ans == "y":
                                        you = name
                                        break
                                    elif ans == "n":
                                        data["chat"].name = name
                                        break
                            else:
                                you = name
                        else:
                            if name != data["chat"].name:
                                you = name
                    if data["chat"].name is None and you != "":
                        if name != you:
                            data["chat"].name = name
                    msg = Message(
                        you == name,
                        datetime.strptime(time, "%d/%m/%Y, %H:%M").timestamp(),
                        time.split(", ")[1].strip(),
                        index
                    )
                    if "<Media omitted>" in message:
                        msg.data = "The media is missing"
                        msg.mime = "media"
                        msg.meta = True
                    elif "(file attached)" in message:
                        mime = MimeTypes()
                        msg.media = True
                        file_path = os.path.join(os.path.dirname(path), message.split("(file attached)")[0].strip())
                        if os.path.isfile(file_path):
                            msg.data = file_path
                            guess = mime.guess_type(file_path)[0]
                            if guess is not None:
                                msg.mime = guess
                            else:
                                msg.mime = "application/octet-stream"
                    else:
                        msg.data = message
                data["chat"].add_message(index, msg)
            else:
                lookback = index - 1
                while lookback not in data["chat"].messages:
                    lookback -= 1
                msg = data["chat"].messages[lookback]
                if msg.media:
                    msg.caption = line.strip()
                else:
                    msg.data += "<br>" + line.strip()
            
            if index % 1000 == 0:
                print(f"Gathering messages & media...({index}/{total_row_number})", end="\r")
    print(f"Gathering messages & media...({total_row_number}/{total_row_number})", end="\r")
    return data
