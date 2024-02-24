#!/usr/bin/python3

import io
import os
import sqlite3
import shutil
import json
import string
import glob
from Whatsapp_Chat_Exporter import exported_handler, android_handler
from Whatsapp_Chat_Exporter import ios_handler, ios_media_handler
from Whatsapp_Chat_Exporter.data_model import ChatStore
from Whatsapp_Chat_Exporter.utility import APPLE_TIME, Crypt, DbType
from Whatsapp_Chat_Exporter.utility import check_update, import_from_json
from argparse import ArgumentParser, SUPPRESS
from datetime import datetime
from sys import exit
try:
    from .__init__ import __version__
except ImportError:
    from Whatsapp_Chat_Exporter.__init__ import __version__


def main():
    parser = ArgumentParser(
        description = 'A customizable Android and iOS/iPadOS WhatsApp database parser that '
                      'will give you the history of your WhatsApp conversations in HTML '
                      'and JSON. Android Backup Crypt12, Crypt14 and Crypt15 supported.',
        epilog = f'WhatsApp Chat Exporter: {__version__} Licensed with MIT'
    )
    parser.add_argument(
        '-a',
        '--android',
        dest='android',
        default=False,
        action='store_true',
        help="Define the target as Android")
    parser.add_argument(
        '-i',
        '--ios',
        '--iphone',
        dest='ios',
        default=False,
        action='store_true',
        help="Define the target as iPhone/iPad")
    parser.add_argument(
        "-e",
        "--exported",
        dest="exported",
        default=None,
        help="Define the target as exported chat file and specify the path to the file"
    )
    parser.add_argument(
        "-w",
        "--wa",
        dest="wa",
        default=None,
        help="Path to contact database (default: wa.db/ContactsV2.sqlite)")
    parser.add_argument(
        "-m",
        "--media",
        dest="media",
        default=None,
        help="Path to WhatsApp media folder (default: WhatsApp)")
    parser.add_argument(
        "-b",
        "--backup",
        dest="backup",
        default=None,
        help="Path to Android (must be used together "
             "with -k)/iOS WhatsApp backup")
    parser.add_argument(
        "-o",
        "--output",
        dest="output",
        default="result",
        help="Output to specific directory (default: result)")
    parser.add_argument(
        '-j',
        '--json',
        dest='json',
        nargs='?',
        default=None,
        type=str,
        const="result.json",
        help="Save the result to a single JSON file (default if present: result.json)")
    parser.add_argument(
        '-d',
        '--db',
        dest='db',
        default=None,
        help="Path to database file (default: msgstore.db/"
             "7c7fba66680ef796b916b067077cc246adacf01d)")
    parser.add_argument(
        '-k',
        '--key',
        dest='key',
        default=None,
        help="Path to key file"
    )
    parser.add_argument(
        "-t",
        "--template",
        dest="template",
        default=None,
        help="Path to custom HTML template"
    )
    parser.add_argument(
        "--embedded",
        dest="embedded",
        default=False,
        action='store_true',
        help=SUPPRESS or "Embed media into HTML file (not yet implemented)"
    )
    parser.add_argument(
        "-s",
        "--showkey",
        dest="showkey",
        default=False,
        action='store_true',
        help="Show the HEX key used to decrypt the database"
    )
    parser.add_argument(
        "-c",
        "--move-media",
        dest="move_media",
        default=False,
        action='store_true',
        help="Move the media directory to output directory if the flag is set, otherwise copy it"
    )
    parser.add_argument(
        "--offline",
        dest="offline",
        default=None,
        help="Relative path to offline static files"
    )
    parser.add_argument(
        "--size",
        "--output-size",
        "--split",
        dest="size",
        nargs='?',
        type=int,
        const=0,
        default=None,
        help="Maximum (rough) size of a single output file in bytes, 0 for auto"
    )
    parser.add_argument(
        "--no-html",
        dest="no_html",
        default=False,
        action='store_true',
        help="Do not output html files"
    )
    parser.add_argument(
        "--check-update",
        dest="check_update",
        default=False,
        action='store_true',
        help="Check for updates (require Internet access)"
    )
    parser.add_argument(
        "--assume-first-as-me",
        dest="assume_first_as_me",
        default=False,
        action='store_true',
        help="Assume the first message in a chat as sent by me (must be used together with -e)"
    )
    parser.add_argument(
        "--no-avatar",
        dest="no_avatar",
        default=False,
        action='store_true',
        help="Do not render avatar in HTML output"
    )
    parser.add_argument(
        "--import",
        dest="import_json",
        default=False,
        action='store_true',
        help="Import JSON file and convert to HTML output"
    )
    parser.add_argument(
        "--business",
        dest="business",
        default=False,
        action='store_true',
        help="Use Whatsapp Business default files (iOS only)"
    )
    parser.add_argument(
        "--preserve-timestamp",
        dest="preserve_timestamp",
        default=False,
        action='store_true',
        help="Preserve the modification timestamp of the extracted files (iOS only)"
    )
    parser.add_argument(
        "--wab",
        "--wa-backup",
        dest="wab",
        default=None,
        help="Path to contact database in crypt15 format"
    )
    parser.add_argument(
        "--time-offset",
        dest="timezone_offset",
        default=0,
        type=int,
        choices=range(-12, 15),
        metavar="{-12 to 14}",
        help="Offset in hours (-12 to 14) for time displayed in the output"
    )
    parser.add_argument(
        "--date",
        dest="filter_date",
        default=None,
        metavar="DATE",
        help="The date filter in specific format (inclusive)"
    )
    parser.add_argument(
        "--date-format",
        dest="filter_date_format",
        default="%Y-%m-%d %H:%M",
        metavar="FORMAT",
        help="The date format for the date filter"
    )
    parser.add_argument(
        "--include",
        dest="filter_chat_include",
        nargs='*',
        metavar="phone number",
        help="Include chats that match the supplied phone number"
    )
    parser.add_argument(
        "--exclude",
        dest="filter_chat_exclude",
        nargs='*',
        metavar="phone number",
        help="Exclude chats that match the supplied phone number"
    )
    parser.add_argument(
        "--per-chat",
        dest="json_per_chat",
        default=False,
        action='store_true',
        help="Output the JSON file per chat"
    )
    args = parser.parse_args()

    # Check for updates
    if args.check_update:
        exit(check_update())

    # Sanity checks
    if args.android and args.ios and args.exported and args.import_json:
        parser.error("You must define only one device type.")
    if not args.android and not args.ios and not args.exported and not args.import_json:
        parser.error("You must define the device type.")
    if args.no_html and not args.json:
        parser.error("You must either specify a JSON output file or enable HTML output.")
    if args.import_json and (args.android or args.ios or args.exported or args.no_html):
        parser.error("You can only use --import with -j and without --no-html.")
    elif args.import_json and not os.path.isfile(args.json):
        parser.error("JSON file not found.")
    if args.android and args.business:
        parser.error("WhatsApp Business is only available on iOS for now.")
    if args.json_per_chat and (
        (args.json[-5:] != ".json" and os.path.isfile(args.json)) or \
        (args.json[-5:] == ".json" and os.path.isfile(args.json[:-5]))
    ):
        parser.error("When --per-chat is enabled, the destination of --json must be a directory.")
    if args.filter_date is not None:
        if " - " in args.filter_date:
            start, end = args.filter_date.split(" - ")
            start = int(datetime.strptime(start, args.filter_date_format).timestamp())
            end = int(datetime.strptime(end, args.filter_date_format).timestamp())
            if start < 1009843200 or end < 1009843200:
                parser.error("WhatsApp was first released in 2009...")
            if start > end:
                parser.error("The start date cannot be a moment after the end date.")
            if args.android:
                args.filter_date = f"BETWEEN {start}000 AND {end}000"
            elif args.ios:
                args.filter_date = f"BETWEEN {start - APPLE_TIME} AND {end - APPLE_TIME}"
        else:
            _timestamp = int(datetime.strptime(args.filter_date[2:], args.filter_date_format).timestamp())
            if _timestamp < 1009843200:
                parser.error("WhatsApp was first released in 2009...")
            if args.filter_date[:2] == "> ":
                if args.android:
                    args.filter_date = f">= {_timestamp}000"
                elif args.ios:
                    args.filter_date = f">= {_timestamp - APPLE_TIME}"
            elif args.filter_date[:2] == "< ":
                if args.android:
                    args.filter_date = f"<= {_timestamp}000"
                elif args.ios:
                    args.filter_date = f"<= {_timestamp - APPLE_TIME}"
            else:
                parser.error("Unsupported date format. See https://wts.knugi.dev/docs?dest=date")
    if args.filter_chat_include is not None and args.filter_chat_exclude is not None:
        parser.error("Chat inclusion and exclusion filters cannot be used together.")
    if args.filter_chat_include is not None:
        for chat in args.filter_chat_include:
            if not chat.isnumeric():
                parser.error("Enter a phone number in the chat filter. See https://wts.knugi.dev/docs?dest=chat")
    if args.filter_chat_exclude is not None:
        for chat in args.filter_chat_exclude:
            if not chat.isnumeric():
                parser.error("Enter a phone number in the chat filter. See https://wts.knugi.dev/docs?dest=chat")
    filter_chat = (args.filter_chat_include, args.filter_chat_exclude)


    data = {}

    if args.android:
        contacts = android_handler.contacts
        messages = android_handler.messages
        media = android_handler.media
        vcard = android_handler.vcard
        create_html = android_handler.create_html
        if args.db is None:
            msg_db = "msgstore.db"
        else:
            msg_db = args.db
        if args.wa is None:
            contact_db = "wa.db"
        else:
            contact_db = args.wa
        if args.key is not None:
            if args.backup is None:
                print("You must specify the backup file with -b")
                exit(1)
            print("Decryption key specified, decrypting WhatsApp backup...")
            if "crypt12" in args.backup:
                crypt = Crypt.CRYPT12
            elif "crypt14" in args.backup:
                crypt = Crypt.CRYPT14
            elif "crypt15" in args.backup:
                crypt = Crypt.CRYPT15
            if os.path.isfile(args.key):
                key = open(args.key, "rb")
            elif all(char in string.hexdigits for char in args.key):
                key = bytes.fromhex(args.key)
            db = open(args.backup, "rb").read()
            if args.wab:
                wab = open(args.wab, "rb").read()
                error_wa = android_handler.decrypt_backup(wab, key, contact_db, crypt, args.showkey, DbType.CONTACT)
                if isinstance(key, io.IOBase):
                    key.seek(0)
            else:
                error_wa = 0
            error_message = android_handler.decrypt_backup(db, key, msg_db, crypt, args.showkey, DbType.MESSAGE)               
            if error_wa != 0:
                error = error_wa
            elif error_message != 0:
                error = error_message
            else:
                error = 0
            if error != 0:
                if error == 1:
                    print("Dependencies of decrypt_backup and/or extract_encrypted_key"
                          " are not present. For details, see README.md.")
                    exit(3)
                elif error == 2:
                    print("Failed when decompressing the decrypted backup. "
                          "Possibly incorrect offsets used in decryption.")
                    exit(4)
                else:
                    print("Unknown error occurred.", error)
                    exit(5)
        if args.media is None:
            args.media = "WhatsApp"

        if os.path.isfile(contact_db):
            with sqlite3.connect(contact_db) as db:
                db.row_factory = sqlite3.Row
                contacts(db, data)
    elif args.ios:
        import sys
        if "--iphone" in sys.argv:
            print(
                "WARNING: The --iphone flag is deprecated and will"
                "be removed in the future. Use --ios instead."
            )
        contacts = ios_handler.contacts
        messages = ios_handler.messages
        media = ios_handler.media
        vcard = ios_handler.vcard
        create_html = android_handler.create_html
        if args.business:
            from Whatsapp_Chat_Exporter.utility import WhatsAppBusinessIdentifier as identifiers
        else:
            from Whatsapp_Chat_Exporter.utility import WhatsAppIdentifier as identifiers
        if args.media is None:
            args.media = identifiers.DOMAIN
        if args.backup is not None:
            if not os.path.isdir(args.media):
                ios_media_handler.extract_media(args.backup, identifiers, args.preserve_timestamp)
            else:
                print("WhatsApp directory already exists, skipping WhatsApp file extraction.")
        if args.db is None:
            msg_db = identifiers.MESSAGE
        else:
            msg_db = args.db
        if args.wa is None:
            contact_db = "ContactsV2.sqlite"
        else:
            contact_db = args.wa
        if os.path.isfile(contact_db):
            with sqlite3.connect(contact_db) as db:
                db.row_factory = sqlite3.Row
                contacts(db, data)

    if not args.exported and not args.import_json:
        if os.path.isfile(msg_db):
            with sqlite3.connect(msg_db) as db:
                db.row_factory = sqlite3.Row
                messages(db, data, args.media, args.timezone_offset, args.filter_date, filter_chat)
                media(db, data, args.media, args.filter_date, filter_chat)
                vcard(db, data, args.media, args.filter_date, filter_chat)
                if args.android:
                    android_handler.calls(db, data, args.timezone_offset, filter_chat)
            if not args.no_html:
                create_html(
                    data,
                    args.output,
                    args.template,
                    args.embedded,
                    args.offline,
                    args.size,
                    args.no_avatar
                )
        else:
            print(
                "The message database does not exist. You may specify the path "
                "to database file with option -d or check your provided path."
            )
            exit(6)

        if os.path.isdir(args.media):
            media_path = os.path.join(args.output, args.media)
            if os.path.isdir(media_path):
                print("\nWhatsApp directory already exists in output directory. Skipping...", end="\n")
            else:
                if not args.move_media:
                    if os.path.isdir(media_path):
                        print("\nWhatsApp directory already exists in output directory. Skipping...", end="\n")
                    else:
                        print("\nCopying media directory...", end="\n")
                        shutil.copytree(args.media, media_path)
                else:
                    try:
                        shutil.move(args.media, f"{args.output}/")
                    except PermissionError:
                        print("\nCannot remove original WhatsApp directory. "
                            "Perhaps the directory is opened?", end="\n")
    elif args.exported:
        exported_handler.messages(args.exported, data, args.assume_first_as_me)
        if not args.no_html:
            android_handler.create_html(
                data,
                args.output,
                args.template,
                args.embedded,
                args.offline,
                args.size
            )
        for file in glob.glob(r'*.*'):
            shutil.copy(file, args.output)
    elif args.import_json:
        import_from_json(args.json, data)
        android_handler.create_html(
            data,
            args.output,
            args.template,
            args.embedded,
            args.offline,
            args.size
        )

    if args.json and not args.import_json:
        if isinstance(data[next(iter(data))], ChatStore):
            data = {jik: chat.to_json() for jik, chat in data.items()}
        if not args.json_per_chat:
            with open(args.json, "w") as f:
                data = json.dumps(data)
                print(f"\nWriting JSON file...({int(len(data)/1024/1024)}MB)")
                f.write(data)
        else:
            if args.json[-5:] == ".json":
                args.json = args.json[:-5]
            total = len(data.keys())
            if not os.path.isdir(args.json):
                os.mkdir(args.json)
            for index, jik in enumerate(data.keys()):
                if data[jik]["name"] is not None:
                    contact = data[jik]["name"].replace('/', '')
                else:
                    contact = jik.replace('+', '')
                with open(f"{args.json}/{contact}.json", "w") as f:
                    f.write(json.dumps(data[jik]))
                    print(f"Writing JSON file...({index + 1}/{total})", end="\r")
            print()
    else:
        print()

    print("Everything is done!")


if __name__ == "__main__":
    main()
