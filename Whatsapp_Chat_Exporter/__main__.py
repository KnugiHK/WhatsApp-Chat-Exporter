#!/usr/bin/python3

import io
import os
import sqlite3
import shutil
import json
import string
import glob
import logging
import importlib.metadata
from Whatsapp_Chat_Exporter import android_crypt, exported_handler, android_handler
from Whatsapp_Chat_Exporter import ios_handler, ios_media_handler
from Whatsapp_Chat_Exporter.data_model import ChatCollection, ChatStore
from Whatsapp_Chat_Exporter.utility import APPLE_TIME, CLEAR_LINE, Crypt, check_update
from Whatsapp_Chat_Exporter.utility import readable_to_bytes, safe_name, bytes_to_readable
from Whatsapp_Chat_Exporter.utility import import_from_json, incremental_merge, DbType
from Whatsapp_Chat_Exporter.utility import telegram_json_format
from argparse import ArgumentParser, SUPPRESS
from datetime import datetime
from getpass import getpass
from sys import exit
from typing import Optional, List, Dict
from Whatsapp_Chat_Exporter.vcards_contacts import ContactsFromVCards


logger = logging.getLogger(__name__)
__version__ = importlib.metadata.version("whatsapp_chat_exporter")
WTSEXPORTER_BANNER = f"""========================================================================================================
                  ██╗    ██╗██╗  ██╗ █████╗ ████████╗███████╗ █████╗ ██████╗ ██████╗
                  ██║    ██║██║  ██║██╔══██╗╚══██╔══╝██╔════╝██╔══██╗██╔══██╗██╔══██╗
                  ██║ █╗ ██║███████║███████║   ██║   ███████╗███████║██████╔╝██████╔╝
                  ██║███╗██║██╔══██║██╔══██║   ██║   ╚════██║██╔══██║██╔═══╝ ██╔═══╝
                  ╚███╔███╔╝██║  ██║██║  ██║   ██║   ███████║██║  ██║██║     ██║
                   ╚══╝╚══╝ ╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   ╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝

 ██████╗██╗  ██╗ █████╗ ████████╗    ███████╗██╗  ██╗██████╗  ██████╗ ██████╗ ████████╗███████╗██████╗
██╔════╝██║  ██║██╔══██╗╚══██╔══╝    ██╔════╝╚██╗██╔╝██╔══██╗██╔═══██╗██╔══██╗╚══██╔══╝██╔════╝██╔══██╗
██║     ███████║███████║   ██║       █████╗   ╚███╔╝ ██████╔╝██║   ██║██████╔╝   ██║   █████╗  ██████╔╝
██║     ██╔══██║██╔══██║   ██║       ██╔══╝   ██╔██╗ ██╔═══╝ ██║   ██║██╔══██╗   ██║   ██╔══╝  ██╔══██╗
╚██████╗██║  ██║██║  ██║   ██║       ███████╗██╔╝ ██╗██║     ╚██████╔╝██║  ██║   ██║   ███████╗██║  ██║
 ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝       ╚══════╝╚═╝  ╚═╝╚═╝      ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚══════╝╚═╝  ╚═╝

         WhatsApp Chat Exporter: A customizable Android and iOS/iPadOS WhatsApp database parser
                                            Version: {__version__}
========================================================================================================"""


def setup_argument_parser() -> ArgumentParser:
    """Set up and return the argument parser with all options."""
    parser = ArgumentParser(
        description='A customizable Android and iOS/iPadOS WhatsApp database parser that '
        'will give you the history of your WhatsApp conversations in HTML '
        'and JSON. Android Backup Crypt12, Crypt14 and Crypt15 supported.',
        epilog=f'WhatsApp Chat Exporter: {__version__} Licensed with MIT. See '
        'https://wts.knugi.dev/docs?dest=osl for all open source licenses.'
    )

    # General options
    parser.add_argument(
        "--debug", dest="debug", default=False, action='store_true',
        help="Enable debug mode"
    )
    # Device type arguments
    device_group = parser.add_argument_group('Device Type')
    device_group.add_argument(
        '-a', '--android', dest='android', default=False, action='store_true',
        help="Define the target as Android"
    )
    device_group.add_argument(
        '-i', '--ios', dest='ios', default=False, action='store_true',
        help="Define the target as iPhone/iPad"
    )
    device_group.add_argument(
        "-e", "--exported", dest="exported", default=None,
        help="Define the target as exported chat file and specify the path to the file"
    )

    # Input file paths
    input_group = parser.add_argument_group('Input Files')
    input_group.add_argument(
        "-w", "--wa", dest="wa", default=None,
        help="Path to contact database (default: wa.db/ContactsV2.sqlite)"
    )
    input_group.add_argument(
        "-m", "--media", dest="media", default=None,
        help="Path to WhatsApp media folder (default: WhatsApp)"
    )
    input_group.add_argument(
        "-b", "--backup", dest="backup", default=None,
        help="Path to Android (must be used together with -k)/iOS WhatsApp backup"
    )
    input_group.add_argument(
        "-d", "--db", dest="db", default=None,
        help="Path to database file (default: msgstore.db/7c7fba66680ef796b916b067077cc246adacf01d)"
    )
    input_group.add_argument(
        "-k", "--key", dest="key", default=None, nargs='?',
        help="Path to key file. If this option is set for crypt15 backup but nothing is specified, you will be prompted to enter the key."
    )
    input_group.add_argument(
        "--call-db", dest="call_db_ios", nargs='?', default=None, type=str,
        const="1b432994e958845fffe8e2f190f26d1511534088",
        help="Path to call database (default: 1b432994e958845fffe8e2f190f26d1511534088) iOS only"
    )
    input_group.add_argument(
        "--wab", "--wa-backup", dest="wab", default=None,
        help="Path to contact database in crypt15 format"
    )

    # Output options
    output_group = parser.add_argument_group('Output Options')
    output_group.add_argument(
        "-o", "--output", dest="output", default="result",
        help="Output to specific directory (default: result)"
    )
    output_group.add_argument(
        '-j', '--json', dest='json', nargs='?', default=None, type=str, const="result.json",
        help="Save the result to a single JSON file (default if present: result.json)"
    )
    output_group.add_argument(
        "--txt", dest="text_format", nargs='?', default=None, type=str, const="result",
        help="Export chats in text format similar to what WhatsApp officially provided (default if present: result/)"
    )
    output_group.add_argument(
        "--no-html", dest="no_html", default=False, action='store_true',
        help="Do not output html files"
    )
    output_group.add_argument(
        "--size", "--output-size", "--split", dest="size", nargs='?', const="0", default=None,
        help="Maximum (rough) size of a single output file in bytes, 0 for auto"
    )
    output_group.add_argument(
        "--no-reply", dest="no_reply_ios", default=False, action='store_true',
        help="Do not process replies (iOS only) (default: handle replies)"
    )

    # JSON formatting options
    json_group = parser.add_argument_group('JSON Options')
    json_group.add_argument(
        '--avoid-encoding-json', dest='avoid_encoding_json', default=False, action='store_true',
        help="Don't encode non-ascii characters in the output JSON files"
    )
    json_group.add_argument(
        '--pretty-print-json', dest='pretty_print_json', default=None, nargs='?', const=2, type=int,
        help="Pretty print the output JSON."
    )
    json_group.add_argument(
        "--tg", "--telegram", dest="telegram", default=False, action='store_true',
        help="Output the JSON in a format compatible with Telegram export (implies json-per-chat)"
    )
    json_group.add_argument(
        "--per-chat", dest="json_per_chat", default=False, action='store_true',
        help="Output the JSON file per chat"
    )
    json_group.add_argument(
        "--import", dest="import_json", default=False, action='store_true',
        help="Import JSON file and convert to HTML output"
    )

    # HTML options
    html_group = parser.add_argument_group('HTML Options')
    html_group.add_argument(
        "-t", "--template", dest="template", default=None,
        help="Path to custom HTML template"
    )
    html_group.add_argument(
        "--embedded", dest="embedded", default=False, action='store_true',
        help=SUPPRESS or "Embed media into HTML file (not yet implemented)"
    )
    html_group.add_argument(
        "--offline", dest="offline", default=None,
        help="Relative path to offline static files"
    )
    html_group.add_argument(
        "--no-avatar", dest="no_avatar", default=False, action='store_true',
        help="Do not render avatar in HTML output"
    )
    html_group.add_argument(
        "--old-theme", dest="telegram_theme", default=False, action='store_true',
        help="Use the old Telegram-alike theme"
    )
    html_group.add_argument(
        "--headline", dest="headline", default="Chat history with ??",
        help="The custom headline for the HTML output. Use '??' as a placeholder for the chat name"
    )

    # Media handling
    media_group = parser.add_argument_group('Media Handling')
    media_group.add_argument(
        "-c", "--move-media", dest="move_media", default=False, action='store_true',
        help="Move the media directory to output directory if the flag is set, otherwise copy it"
    )
    media_group.add_argument(
        "--create-separated-media", dest="separate_media", default=False, action='store_true',
        help="Create a copy of the media seperated per chat in <MEDIA>/separated/ directory"
    )

    # Filtering options
    filter_group = parser.add_argument_group('Filtering Options')
    filter_group.add_argument(
        "--time-offset", dest="timezone_offset", default=0, type=int, choices=range(-12, 15),
        metavar="{-12 to 14}", help="Offset in hours (-12 to 14) for time displayed in the output"
    )
    filter_group.add_argument(
        "--date", dest="filter_date", default=None, metavar="DATE",
        help="The date filter in specific format (inclusive)"
    )
    filter_group.add_argument(
        "--date-format", dest="filter_date_format", default="%Y-%m-%d %H:%M", metavar="FORMAT",
        help="The date format for the date filter"
    )
    filter_group.add_argument(
        "--include", dest="filter_chat_include", nargs='*', metavar="phone number",
        help="Include chats that match the supplied phone number"
    )
    filter_group.add_argument(
        "--exclude", dest="filter_chat_exclude", nargs='*', metavar="phone number",
        help="Exclude chats that match the supplied phone number"
    )
    filter_group.add_argument(
        "--dont-filter-empty", dest="filter_empty", default=True, action='store_false',
        help=("By default, the exporter will not render chats with no valid message. "
              "Setting this flag will cause the exporter to render those. "
              "This is useful if chat(s) are missing from the output")
    )

    # Contact enrichment
    contact_group = parser.add_argument_group('Contact Enrichment')
    contact_group.add_argument(
        "--enrich-from-vcards", dest="enrich_from_vcards", default=None,
        help="Path to an exported vcf file from Google contacts export. Add names missing from WhatsApp's default database"
    )
    contact_group.add_argument(
        "--default-country-code", dest="default_country_code", default=None,
        help="Use with --enrich-from-vcards. When numbers in the vcf file does not have a country code, this will be used. 1 is for US, 66 for Thailand etc. Most likely use the number of your own country"
    )

    # Incremental merging
    inc_merging_group = parser.add_argument_group('Incremental Merging')
    inc_merging_group.add_argument(
        "--incremental-merge",
        dest="incremental_merge",
        default=False,
        action='store_true',
        help=("Performs an incremental merge of two exports. "
              "Requires setting both --source-dir and --target-dir. "
              "The chats (JSON files only) and media from the source directory will be merged into the target directory. "
              "No chat messages or media will be deleted from the target directory; only new chat messages and media will be added to it. "
              "This enables chat messages and media to be deleted from the device to free up space, while ensuring they are preserved in the exported backups."
              )
    )
    inc_merging_group.add_argument(
        "--source-dir",
        dest="source_dir",
        default=None,
        help="Sets the source directory. Used for performing incremental merges."
    )
    inc_merging_group.add_argument(
        "--target-dir",
        dest="target_dir",
        default=None,
        help="Sets the target directory. Used for performing incremental merges."
    )

    # Miscellaneous
    misc_group = parser.add_argument_group('Miscellaneous')
    misc_group.add_argument(
        "-s", "--showkey", dest="showkey", default=False, action='store_true',
        help="Show the HEX key used to decrypt the database"
    )
    misc_group.add_argument(
        "--check-update", dest="check_update", default=False, action='store_true',
        help="Check for updates (require Internet access)"
    )
    misc_group.add_argument(
        "--assume-first-as-me", dest="assume_first_as_me", default=False, action='store_true',
        help="Assume the first message in a chat as sent by me (must be used together with -e)"
    )
    misc_group.add_argument(
        "--business", dest="business", default=False, action='store_true',
        help="Use Whatsapp Business default files (iOS only)"
    )
    misc_group.add_argument(
        "--decrypt-chunk-size", dest="decrypt_chunk_size", default=1 * 1024 * 1024, type=int,
        help="Specify the chunk size for decrypting iOS backup, which may affect the decryption speed."
    )
    misc_group.add_argument(
        "--max-bruteforce-worker", dest="max_bruteforce_worker", default=10, type=int,
        help="Specify the maximum number of worker for bruteforce decryption."
    )
    misc_group.add_argument(
        "--no-banner", dest="no_banner", default=False, action='store_true',
        help="Do not show the banner"
    )

    return parser


def validate_args(parser: ArgumentParser, args) -> None:
    """Validate command line arguments and modify them if needed."""
    # Basic validation checks
    if args.android and args.ios and args.exported and args.import_json:
        parser.error("You must define only one device type.")
    if not args.android and not args.ios and not args.exported and not args.import_json:
        parser.error("You must define the device type.")
    if args.no_html and not args.json and not args.text_format:
        parser.error(
            "You must either specify a JSON output file, text file output directory or enable HTML output.")
    if args.import_json and (args.android or args.ios or args.exported or args.no_html):
        parser.error(
            "You can only use --import with -j and without --no-html, -a, -i, -e.")
    elif args.import_json and not os.path.isfile(args.json):
        parser.error("JSON file not found.")
    if args.incremental_merge and (args.source_dir is None or args.target_dir is None):
        parser.error(
            "You must specify both --source-dir and --target-dir for incremental merge.")
    if args.android and args.business:
        parser.error("WhatsApp Business is only available on iOS for now.")
    if "??" not in args.headline:
        parser.error("--headline must contain '??' for replacement.")

    # JSON validation
    if args.json_per_chat and args.json and (
        (args.json.endswith(".json") and os.path.isfile(args.json)) or
        (not args.json.endswith(".json") and os.path.isfile(args.json))
    ):
        parser.error(
            "When --per-chat is enabled, the destination of --json must be a directory.")

    # vCards validation
    if args.enrich_from_vcards is not None and args.default_country_code is None:
        parser.error(
            "When --enrich-from-vcards is provided, you must also set --default-country-code")

    # Size validation and conversion
    if args.size is not None:
        try:
            args.size = readable_to_bytes(args.size)
        except ValueError:
            parser.error(
                "The value for --split must be pure bytes or use a proper unit (e.g., 1048576 or 1MB)"
            )

    # Date filter validation and processing
    if args.filter_date is not None:
        process_date_filter(parser, args)

    # Crypt15 key validation
    if args.key is None and args.backup is not None and args.backup.endswith("crypt15"):
        args.key = getpass("Enter your encryption key: ")

    # Theme validation
    if args.telegram_theme:
        args.template = "whatsapp_old.html"

    # Chat filter validation
    if args.filter_chat_include is not None and args.filter_chat_exclude is not None:
        parser.error(
            "Chat inclusion and exclusion filters cannot be used together.")

    validate_chat_filters(parser, args.filter_chat_include)
    validate_chat_filters(parser, args.filter_chat_exclude)


def validate_chat_filters(parser: ArgumentParser, chat_filter: Optional[List[str]]) -> None:
    """Validate chat filters to ensure they contain only phone numbers."""
    if chat_filter is not None:
        for chat in chat_filter:
            if not chat.isnumeric():
                parser.error(
                    "Enter a phone number in the chat filter. See https://wts.knugi.dev/docs?dest=chat")


def process_date_filter(parser: ArgumentParser, args) -> None:
    """Process and validate date filter arguments."""
    if " - " in args.filter_date:
        start, end = args.filter_date.split(" - ")
        start = int(datetime.strptime(
            start, args.filter_date_format).timestamp())
        end = int(datetime.strptime(end, args.filter_date_format).timestamp())

        if start < 1009843200 or end < 1009843200:
            parser.error("WhatsApp was first released in 2009...")
        if start > end:
            parser.error(
                "The start date cannot be a moment after the end date.")

        if args.android:
            args.filter_date = f"BETWEEN {start}000 AND {end}000"
        elif args.ios:
            args.filter_date = f"BETWEEN {start - APPLE_TIME} AND {end - APPLE_TIME}"
    else:
        process_single_date_filter(parser, args)


def process_single_date_filter(parser: ArgumentParser, args) -> None:
    """Process single date comparison filters."""
    if len(args.filter_date) < 3:
        parser.error(
            "Unsupported date format. See https://wts.knugi.dev/docs?dest=date")

    _timestamp = int(datetime.strptime(
        args.filter_date[2:], args.filter_date_format).timestamp())

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
        parser.error(
            "Unsupported date format. See https://wts.knugi.dev/docs?dest=date")


def setup_contact_store(args) -> Optional['ContactsFromVCards']:
    """Set up and return a contact store if needed."""
    if args.enrich_from_vcards is not None:
        contact_store = ContactsFromVCards()
        contact_store.load_vcf_file(
            args.enrich_from_vcards, args.default_country_code)
        return contact_store
    return None


def decrypt_android_backup(args) -> int:
    """Decrypt Android backup files and return error code."""
    if args.key is None or args.backup is None:
        logger.error(f"You must specify the backup file with -b and a key with -k{CLEAR_LINE}")
        return 1

    logger.info(f"Decryption key specified, decrypting WhatsApp backup...{CLEAR_LINE}")

    # Determine crypt type
    if "crypt12" in args.backup:
        crypt = Crypt.CRYPT12
    elif "crypt14" in args.backup:
        crypt = Crypt.CRYPT14
    elif "crypt15" in args.backup:
        crypt = Crypt.CRYPT15
    else:
        logger.error(
            f"Unknown backup format. The backup file must be crypt12, crypt14 or crypt15.{CLEAR_LINE}")
        return 1

    # Get key
    keyfile_stream = False
    if not os.path.isfile(args.key) and all(char in string.hexdigits for char in args.key.replace(" ", "")):
        key = bytes.fromhex(args.key.replace(" ", ""))
    else:
        key = open(args.key, "rb")
        keyfile_stream = True

    # Read backup
    db = open(args.backup, "rb").read()

    # Process WAB if provided
    error_wa = 0
    if args.wab:
        wab = open(args.wab, "rb").read()
        error_wa = android_crypt.decrypt_backup(
            wab,
            key,
            args.wa,
            crypt,
            args.showkey,
            DbType.CONTACT,
            keyfile_stream=keyfile_stream,
            max_worker=args.max_bruteforce_worker
        )
        if isinstance(key, io.IOBase):
            key.seek(0)

    # Decrypt message database
    error_message = android_crypt.decrypt_backup(
        db,
        key,
        args.db,
        crypt,
        args.showkey,
        DbType.MESSAGE,
        keyfile_stream=keyfile_stream,
        max_worker=args.max_bruteforce_worker
    )

    # Handle errors
    if error_wa != 0:
        return error_wa
    return error_message


def handle_decrypt_error(error: int) -> None:
    """Handle decryption errors with appropriate messages."""
    if error == 1:
        logger.error("Dependencies of decrypt_backup and/or extract_encrypted_key"
                     " are not present. For details, see README.md.\n")
        exit(3)
    elif error == 2:
        logger.error("Failed when decompressing the decrypted backup. "
                     "Possibly incorrect offsets used in decryption.\n")
        exit(4)
    else:
        logger.error("Unknown error occurred.\n")
        exit(5)


def process_contacts(args, data: ChatCollection) -> None:
    """Process contacts from the database."""
    contact_db = args.wa if args.wa else "wa.db" if args.android else "ContactsV2.sqlite"

    if os.path.isfile(contact_db):
        with sqlite3.connect(contact_db) as db:
            db.row_factory = sqlite3.Row
            if args.android:
                android_handler.contacts(db, data, args.enrich_from_vcards)
            else:
                ios_handler.contacts(db, data)


def process_messages(args, data: ChatCollection) -> None:
    """Process messages, media and vcards from the database."""
    msg_db = args.db if args.db else "msgstore.db" if args.android else args.identifiers.MESSAGE

    if not os.path.isfile(msg_db):
        logger.error(
            "The message database does not exist. You may specify the path "
            "to database file with option -d or check your provided path.\n"
        )
        exit(6)

    filter_chat = (args.filter_chat_include, args.filter_chat_exclude)

    with sqlite3.connect(msg_db) as db:
        db.row_factory = sqlite3.Row

        # Process messages
        if args.android:
            message_handler = android_handler
        else:
            message_handler = ios_handler

        message_handler.messages(
            db, data, args.media, args.timezone_offset, args.filter_date,
            filter_chat, args.filter_empty, args.no_reply_ios
        )

        # Process media
        message_handler.media(
            db, data, args.media, args.filter_date,
            filter_chat, args.filter_empty, args.separate_media
        )

        # Process vcards
        message_handler.vcard(
            db, data, args.media, args.filter_date,
            filter_chat, args.filter_empty
        )

        # Process calls
        process_calls(args, db, data, filter_chat)


def process_calls(args, db, data: ChatCollection, filter_chat) -> None:
    """Process call history if available."""
    if args.android:
        android_handler.calls(db, data, args.timezone_offset, filter_chat)
    elif args.ios and args.call_db_ios is not None:
        with sqlite3.connect(args.call_db_ios) as cdb:
            cdb.row_factory = sqlite3.Row
            ios_handler.calls(cdb, data, args.timezone_offset, filter_chat)


def handle_media_directory(args) -> None:
    """Handle media directory copying or moving."""
    if os.path.isdir(args.media):
        media_path = os.path.join(args.output, args.media)

        if os.path.isdir(media_path):
            logger.info(
                f"WhatsApp directory already exists in output directory. Skipping...{CLEAR_LINE}")
        else:
            if args.move_media:
                try:
                    logger.info(f"Moving media directory...\r")
                    shutil.move(args.media, f"{args.output}/")
                    logger.info(f"Media directory has been moved to the output directory{CLEAR_LINE}")
                except PermissionError:
                    logger.warning("Cannot remove original WhatsApp directory. "
                                   "Perhaps the directory is opened?\n")
            else:
                logger.info(f"Copying media directory...\r")
                shutil.copytree(args.media, media_path)
                logger.info(f"Media directory has been copied to the output directory{CLEAR_LINE}")


def create_output_files(args, data: ChatCollection) -> None:
    """Create output files in the specified formats."""
    # Create HTML files if requested
    if not args.no_html:
        android_handler.create_html(
            data,
            args.output,
            args.template,
            args.embedded,
            args.offline,
            args.size,
            args.no_avatar,
            args.telegram_theme,
            args.headline
        )

    # Create text files if requested
    if args.text_format:
        logger.info(f"Writing text file...{CLEAR_LINE}")
        android_handler.create_txt(data, args.text_format)

    # Create JSON files if requested
    if args.json and not args.import_json:
        export_json(args, data)


def export_json(args, data: ChatCollection) -> None:
    """Export data to JSON format."""
    # TODO: remove all non-target chats from data if filtering is applied?
    # Convert ChatStore objects to JSON
    if isinstance(data.get(next(iter(data), None)), ChatStore):
        data = {jik: chat.to_json() for jik, chat in data.items()}

    # Export as a single file or per chat
    if not args.json_per_chat and not args.telegram:
        export_single_json(args, data)
    else:
        export_multiple_json(args, data)


def export_single_json(args, data: Dict) -> None:
    """Export data to a single JSON file."""
    with open(args.json, "w") as f:
        json_data = json.dumps(
            data,
            ensure_ascii=not args.avoid_encoding_json,
            indent=args.pretty_print_json
        )
        logger.info(f"Writing JSON file...\r")
        f.write(json_data)
    logger.info(f"JSON file saved...({bytes_to_readable(len(json_data))}){CLEAR_LINE}")


def export_multiple_json(args, data: Dict) -> None:
    """Export data to multiple JSON files, one per chat."""
    # Adjust output path if needed
    json_path = args.json[:-5] if args.json.endswith(".json") else args.json

    # Create directory if it doesn't exist
    if not os.path.isdir(json_path):
        os.makedirs(json_path, exist_ok=True)

    # Export each chat
    total = len(data.keys())
    for index, jik in enumerate(data.keys()):
        if data[jik]["name"] is not None:
            contact = data[jik]["name"].replace('/', '')
        else:
            contact = jik.replace('+', '')

        if args.telegram:
            messages = telegram_json_format(jik, data[jik], args.timezone_offset)
        else:
            messages = {jik: data[jik]}
        with open(f"{json_path}/{safe_name(contact)}.json", "w") as f:
            file_content = json.dumps(
                messages,
                ensure_ascii=not args.avoid_encoding_json,
                indent=args.pretty_print_json
            )
            f.write(file_content)
            logger.info(f"Writing JSON file...({index + 1}/{total})\r")


def process_exported_chat(args, data: ChatCollection) -> None:
    """Process an exported chat file."""
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
            args.telegram_theme,
            args.headline
        )

    # Copy files to output directory
    for file in glob.glob(r'*.*'):
        shutil.copy(file, args.output)


def setup_logging(level):
    log_handler_stdout = logging.StreamHandler()
    log_handler_stdout.terminator = ""
    handlers = [log_handler_stdout]
    if level == logging.DEBUG:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        handlers.append(logging.FileHandler(f"wtsexpoter-debug-{timestamp}.log", mode="w"))
    logging.basicConfig(
        level=level,
        format="[%(levelname)s] %(message)s",
        handlers=handlers
    )


def main():
    """Main function to run the WhatsApp Chat Exporter."""
    # Set up and parse arguments
    parser = setup_argument_parser()
    args = parser.parse_args()

    # Check for updates
    if args.check_update:
        exit(check_update())

    # Validate arguments
    validate_args(parser, args)

    # Print banner if not suppressed
    if not args.no_banner:
        print(WTSEXPORTER_BANNER)

    if args.debug:
        setup_logging(logging.DEBUG)
        logger.debug("Debug mode enabled.\n")
    else:
        setup_logging(logging.INFO)

    # Create output directory if it doesn't exist
    os.makedirs(args.output, exist_ok=True)

    # Initialize data collection
    data = ChatCollection()

    # Set up contact store for vCard enrichment if needed
    contact_store = setup_contact_store(args)

    if args.import_json:
        # Import from JSON
        import_from_json(args.json, data)
        android_handler.create_html(
            data,
            args.output,
            args.template,
            args.embedded,
            args.offline,
            args.size,
            args.no_avatar,
            args.telegram_theme,
            args.headline
        )
    elif args.exported:
        # Process exported chat
        process_exported_chat(args, data)
    else:
        # Process Android or iOS data
        if args.android:
            # Set default media path if not provided
            if args.media is None:
                args.media = "WhatsApp"

            # Set default DB paths if not provided
            if args.db is None:
                args.db = "msgstore.db"
            if args.wa is None:
                args.wa = "wa.db"

            # Decrypt backup if needed
            if args.key is not None:
                error = decrypt_android_backup(args)
                if error != 0:
                    handle_decrypt_error(error)
        elif args.ios:
            # Set up identifiers based on business flag
            if args.business:
                from Whatsapp_Chat_Exporter.utility import WhatsAppBusinessIdentifier as identifiers
            else:
                from Whatsapp_Chat_Exporter.utility import WhatsAppIdentifier as identifiers
            args.identifiers = identifiers

            # Set default media path if not provided
            if args.media is None:
                args.media = identifiers.DOMAIN

            # Extract media from backup if needed
            if args.backup is not None:
                if not os.path.isdir(args.media):
                    ios_media_handler.extract_media(
                        args.backup, identifiers, args.decrypt_chunk_size)
                else:
                    logger.info(
                        f"WhatsApp directory already exists, skipping WhatsApp file extraction.{CLEAR_LINE}")

            # Set default DB paths if not provided
            if args.db is None:
                args.db = identifiers.MESSAGE
            if args.wa is None:
                args.wa = "ContactsV2.sqlite"

        if args.incremental_merge:
            incremental_merge(
                args.source_dir,
                args.target_dir,
                args.media,
                args.pretty_print_json,
                args.avoid_encoding_json
            )
            logger.info(f"Incremental merge completed successfully.{CLEAR_LINE}")
        else:
            # Process contacts
            process_contacts(args, data)

            # Enrich contacts from vCards if needed
            if args.android and contact_store and not contact_store.is_empty():
                contact_store.enrich_from_vcards(data)

            # Process messages, media, and calls
            process_messages(args, data)

            # Create output files
            create_output_files(args, data)

            # Handle media directory
            handle_media_directory(args)

        logger.info("Everything is done!")


if __name__ == "__main__":
    main()
