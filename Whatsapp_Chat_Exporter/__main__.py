#!/usr/bin/python3

import io
import os
import sqlite3
import shutil
import json
import string
import glob
try:
    import vobject
except ModuleNotFoundError:
    vcards_deps_installed = False
else:
    from Whatsapp_Chat_Exporter.vcards_contacts import ContactsFromVCards
    vcards_deps_installed = True
from Whatsapp_Chat_Exporter import exported_handler, android_handler
from Whatsapp_Chat_Exporter import ios_handler, ios_media_handler
from Whatsapp_Chat_Exporter.data_model import ChatStore
from Whatsapp_Chat_Exporter.utility import APPLE_TIME, Crypt, DbType, chat_is_empty, readable_to_bytes
from Whatsapp_Chat_Exporter.utility import check_update, import_from_json, sanitize_filename, bytes_to_readable
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
        epilog = f'WhatsApp Chat Exporter: {__version__} Licensed with MIT. See '
                  'https://wts.knugi.dev/docs?dest=osl for all open source licenses.'
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
        '--avoid-encoding-json',
        dest='avoid_encoding_json',
        default=False,
        action='store_true',
        help="Don't encode non-ascii characters in the output JSON files")
    parser.add_argument(
        '--pretty-print-json',
        dest='pretty_print_json',
        default=None,
        nargs='?',
        const=2,
        type=int,
        help="Pretty print the output JSON.")
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
        "--dont-filter-empty",
        dest="filter_empty",
        default=True,
        action='store_false',
        help="By default, the exporter will not render chats with no valid message. Setting this flag will cause the exporter to render those."
    )
    parser.add_argument(
        "--per-chat",
        dest="json_per_chat",
        default=False,
        action='store_true',
        help="Output the JSON file per chat"
    )
    parser.add_argument(
        "--create-separated-media",
        dest="separate_media",
        default=False,
        action='store_true',
        help="Create a copy of the media seperated per chat in <MEDIA>/separated/ directory"
    )
    parser.add_argument(
        "--decrypt-chunk-size",
        dest="decrypt_chunk_size",
        default=1 * 1024 * 1024,
        type=int,
        help="Specify the chunk size for decrypting iOS backup, which may affect the decryption speed."
    )
    parser.add_argument(
        "--enrich-from-vcards",
        dest="enrich_from_vcards",
        default=None,
        help="Path to an exported vcf file from Google contacts export. Add names missing from WhatsApp's default database"
    )
    parser.add_argument(
        "--default-country-code",
        dest="default_contry_code",
        default=None,
        help="Use with --enrich-from-vcards. When numbers in the vcf file does not have a country code, this will be used. 1 is for US, 66 for Thailand etc. Most likely use the number of your own country"
    )
    parser.add_argument(
        "--txt",
        dest="text_format",
        nargs='?',
        default=None,
        type=str,
        const="result",
        help="Export chats in text format similar to what WhatsApp officially provided (default if present: result/)")

    args = parser.parse_args()

    # Check for updates
    if args.check_update:
        exit(check_update())

    # Sanity checks
    if args.android and args.ios and args.exported and args.import_json:
        parser.error("You must define only one device type.")
    if not args.android and not args.ios and not args.exported and not args.import_json:
        parser.error("You must define the device type.")
    if args.no_html and not args.json and not args.text_format:
        parser.error("You must either specify a JSON output file, text file output directory or enable HTML output.")
    if args.import_json and (args.android or args.ios or args.exported or args.no_html):
        parser.error("You can only use --import with -j and without --no-html, -a, -i, -e.")
    elif args.import_json and not os.path.isfile(args.json):
        parser.error("JSON file not found.")
    if args.android and args.business:
        parser.error("WhatsApp Business is only available on iOS for now.")
    if args.json_per_chat and (
        (args.json[-5:] != ".json" and os.path.isfile(args.json)) or \
        (args.json[-5:] == ".json" and os.path.isfile(args.json[:-5]))
    ):
        parser.error("When --per-chat is enabled, the destination of --json must be a directory.")
    if args.enrich_from_vcards is not None and args.default_contry_code is None:
        parser.error("When --enrich-from-vcards is provided, you must also set --default-country-code")
    if args.size is not None and not isinstance(args.size, int) and not args.size.isnumeric():
        try:
            args.size = readable_to_bytes(args.size)
        except ValueError:
            parser.error("The value for --split must be ended in pure bytes or with a proper unit (e.g., 1048576 or 1MB)")
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

    if args.enrich_from_vcards is not None:
        if not vcards_deps_installed:
            parser.error(
                "You don't have the dependency to enrich contacts with vCard.\n"
                "Read more on how to deal with enriching contacts:\n"
                "https://github.com/KnugiHK/Whatsapp-Chat-Exporter/blob/main/README.md#usage"
            )
        contact_store = ContactsFromVCards()
        contact_store.load_vcf_file(args.enrich_from_vcards, args.default_contry_code)

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
                ios_media_handler.extract_media(args.backup, identifiers, args.decrypt_chunk_size)
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
                media(db, data, args.media, args.filter_date, filter_chat, args.separate_media)
                vcard(db, data, args.media, args.filter_date, filter_chat)
                if args.android:
                    android_handler.calls(db, data, args.timezone_offset, filter_chat)
            if not args.no_html:
                if args.enrich_from_vcards is not None and not contact_store.is_empty():
                    contact_store.enrich_from_vcards(data)

                create_html(
                    data,
                    args.output,
                    args.template,
                    args.embedded,
                    args.offline,
                    args.size,
                    args.no_avatar,
                    args.filter_empty
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
                args.size,
                args.no_avatar,
                args.filter_empty
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
            args.size,
            args.no_avatar,
            args.filter_empty
        )

    if args.text_format:
        print("Writing text file...")
        android_handler.create_txt(data, args.text_format)

    if args.json and not args.import_json:
        if args.filter_empty:
            data = {k: v for k, v in data.items() if not chat_is_empty(v)}

        if args.enrich_from_vcards is not None and not contact_store.is_empty():
            contact_store.enrich_from_vcards(data)

        if isinstance(data[next(iter(data))], ChatStore):
            data = {jik: chat.to_json() for jik, chat in data.items()}
            
        if not args.json_per_chat:
            with open(args.json, "w") as f:
                data = json.dumps(
                    data,
                    ensure_ascii=not args.avoid_encoding_json,
                    indent=args.pretty_print_json
                )
                print(f"\nWriting JSON file...({bytes_to_readable(len(data))})")
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
                with open(f"{args.json}/{sanitize_filename(contact)}.json", "w") as f:
                    file_content_to_write = json.dumps({jik: data[jik]}, ensure_ascii=not args.avoid_encoding_json, indent=2 if args.pretty_print_json else None)
                    f.write(file_content_to_write)
                    print(f"Writing JSON file...({index + 1}/{total})", end="\r")
            print()
    else:
        print()

    print("Everything is done!")


if __name__ == "__main__":
    main()
