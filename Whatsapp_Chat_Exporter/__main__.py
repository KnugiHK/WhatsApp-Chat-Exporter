#!/usr/bin/python3

import os
import sqlite3
import shutil
import json
import string
import glob
from Whatsapp_Chat_Exporter import extract_exported, extract_iphone
from Whatsapp_Chat_Exporter import extract, extract_iphone_media
from Whatsapp_Chat_Exporter.data_model import ChatStore
from Whatsapp_Chat_Exporter.utility import Crypt, check_update, import_from_json
from argparse import ArgumentParser, SUPPRESS
from sys import exit
try:
    from .__init__ import __version__
except ImportError:
    from Whatsapp_Chat_Exporter.__init__ import __version__


def main():
    parser = ArgumentParser(
        description = 'A customizable Android and iPhone WhatsApp database parser that '
                      'will give you the history of your WhatsApp conversations inHTML '
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
        '--iphone',
        '--ios',
        dest='iphone',
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
             "with -k)/iPhone WhatsApp backup")
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
    args = parser.parse_args()

    # Check for updates
    if args.check_update:
        exit(check_update())

    # Sanity checks
    if args.android and args.iphone and args.exported and args.import_json:
        print("You must define only one device type.")
        exit(1)
    if not args.android and not args.iphone and not args.exported and not args.import_json:
        print("You must define the device type.")
        exit(1)
    if args.no_html and not args.json:
        print("You must either specify a JSON output file or enable HTML output.")
        exit(1)
    if args.import_json and (args.android or args.iphone or args.exported or args.no_html):
        print("You can only use --import with -j and without --no-html.")
        exit(1)
    elif args.import_json and not os.path.isfile(args.json):
        print("JSON file not found.")
        exit(1)

    data = {}

    if args.android:
        contacts = extract.contacts
        messages = extract.messages
        media = extract.media
        vcard = extract.vcard
        create_html = extract.create_html
        if args.db is None:
            msg_db = "msgstore.db"
        else:
            msg_db = args.db
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
            error = extract.decrypt_backup(db, key, msg_db, crypt, args.showkey)
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
        if args.wa is None:
            contact_db = "wa.db"
        else:
            contact_db = args.wa
        if args.media is None:
            args.media = "WhatsApp"

        if os.path.isfile(contact_db):
            with sqlite3.connect(contact_db) as db:
                db.row_factory = sqlite3.Row
                contacts(db, data)
    elif args.iphone:
        import sys
        if "--iphone" in sys.argv:
            print(
                "WARNING: The --iphone flag is deprecated and will"
                "be removed in the future. Use --ios instead."
            )
        contacts = extract_iphone.contacts
        messages = extract_iphone.messages
        media = extract_iphone.media
        vcard = extract_iphone.vcard
        create_html = extract.create_html
        if args.media is None:
            args.media = "AppDomainGroup-group.net.whatsapp.WhatsApp.shared"
        if args.backup is not None:
            if not os.path.isdir(args.media):
                extract_iphone_media.extract_media(args.backup)
            else:
                print("WhatsApp directory already exists, skipping WhatsApp file extraction.")
        if args.db is None:
            msg_db = "7c7fba66680ef796b916b067077cc246adacf01d"
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
                messages(db, data, args.media)
                media(db, data, args.media)
                vcard(db, data)
                if args.android:
                    extract.calls(db, data)
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
            exit(2)

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
        extract_exported.messages(args.exported, data, args.assume_first_as_me)
        if not args.no_html:
            extract.create_html(
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
        extract.create_html(
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
        with open(args.json, "w") as f:
            data = json.dumps(data)
            print(f"\nWriting JSON file...({int(len(data)/1024/1024)}MB)")
            f.write(data)
    else:
        print()

    print("Everything is done!")


if __name__ == "__main__":
    main()
