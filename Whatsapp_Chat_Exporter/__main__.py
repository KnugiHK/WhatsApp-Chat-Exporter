from .__init__ import __version__
from Whatsapp_Chat_Exporter import extract, extract_iphone
from Whatsapp_Chat_Exporter import extract_iphone_media
from optparse import OptionParser
import os
import sqlite3
import shutil
import json


def main():
    parser = OptionParser(version=f"Whatsapp Chat Exporter: {__version__}")
    parser.add_option(
        '-a',
        '--android',
        dest='android',
        default=False,
        action='store_true',
        help="Define the target as Android")
    parser.add_option(
        '-i',
        '--iphone',
        dest='iphone',
        default=False,
        action='store_true',
        help="Define the target as iPhone")
    parser.add_option(
        "-w",
        "--wa",
        dest="wa",
        default=None,
        help="Path to contact database")
    parser.add_option(
        "-m",
        "--media",
        dest="media",
        default=None,
        help="Path to WhatsApp media folder")
    parser.add_option(
        "-b",
        "--backup",
        dest="backup",
        default=None,
        help="Path to Android (must be used together "
             "with -k)/iPhone WhatsApp backup")
    parser.add_option(
        "-o",
        "--output",
        dest="output",
        default="result",
        help="Output to specific directory")
    parser.add_option(
        '-j',
        '--json',
        dest='json',
        default=False,
        action='store_true',
        help="Save the result to a single JSON file")
    parser.add_option(
        '-d',
        '--db',
        dest='db',
        default=None,
        help="Path to database file")
    parser.add_option(
        '-k',
        '--key',
        dest='key',
        default=None,
        help="Path to key file"
    )
    parser.add_option(
        "-t",
        "--template",
        dest="template",
        default=None,
        help="Path to custom HTML template")
    (options, args) = parser.parse_args()

    if options.android and options.iphone:
        print("You must define only one device type.")
        exit()
    if not options.android and not options.iphone:
        print("You must define the device type.")
        exit()
    data = {}

    if options.android:
        contacts = extract.contacts
        messages = extract.messages
        media = extract.media
        vcard = extract.vcard
        create_html = extract.create_html
        if options.db is None:
            msg_db = "msgstore.db"
        else:
            msg_db = options.db
        if options.key is not None:
            if options.backup is None:
                print("You must specify the backup file with -b")
                return False
            print("Decryption key specified, decrypting WhatsApp backup...")
            key = open(options.key, "rb").read()
            db = open(options.backup, "rb").read()
            is_crypt14 = False if "crypt12" in options.backup else True
            if not extract.decrypt_backup(db, key, msg_db, is_crypt14):
                print("Dependencies of decrypt_backup are not "
                      "present. For details, see README.md")
                return False
        if options.wa is None:
            contact_db = "wa.db"
        else:
            contact_db = options.wa
        if options.media is None:
            options.media = "WhatsApp"

        if len(args) == 1:
            msg_db = args[0]

        if os.path.isfile(contact_db):
            with sqlite3.connect(contact_db) as db:
                contacts(db, data)

    elif options.iphone:
        messages = extract_iphone.messages
        media = extract_iphone.media
        vcard = extract_iphone.vcard
        create_html = extract_iphone.create_html
        if options.backup is not None:
            extract_iphone_media.extract_media(options.backup)
        if options.db is None:
            msg_db = "7c7fba66680ef796b916b067077cc246adacf01d"
        else:
            msg_db = options.db
        if options.wa is None:
            contact_db = "ContactsV2.sqlite"
        else:
            contact_db = options.wa
        if options.media is None:
            options.media = "Message"

        if len(args) == 1:
            msg_db = args[0]

    if os.path.isfile(msg_db):
        with sqlite3.connect(msg_db) as db:
            messages(db, data)
            media(db, data, options.media)
            vcard(db, data)
        create_html(data, options.output, options.template)

    if not os.path.isdir(f"{options.output}/{options.media}"):
        shutil.move(options.media, f"{options.output}/")

    if options.json:
        with open("result.json", "w") as f:
            data = json.dumps(data)
            print(f"\nWriting JSON file...({int(len(data)/1024/1024)}MB)")
            f.write(data)
    else:
        print()

    print("Everything is done!")
