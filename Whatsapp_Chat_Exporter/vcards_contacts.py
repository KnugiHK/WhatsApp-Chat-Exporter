import vobject
import re
import quopri
from typing import List, TypedDict
from Whatsapp_Chat_Exporter.data_model import ChatStore
from Whatsapp_Chat_Exporter.utility import Device


class ExportedContactNumbers(TypedDict):
    full_name: str
    numbers: List[str]


class ContactsFromVCards:
    def __init__(self) -> None:
        self.contact_mapping = []

    def is_empty(self):
        return self.contact_mapping == []

    def load_vcf_file(self, vcf_file_path: str, default_country_code: str):
        self.contact_mapping = read_vcards_file(vcf_file_path, default_country_code)

    def enrich_from_vcards(self, chats):
        for number, name in self.contact_mapping:
            # short number must be a bad contact, lets skip it
            if len(number) <= 5:
                continue               
            chats_search = filter_chats_by_prefix(chats, number).values()
            if chats_search:
                for chat in chats_search:
                    if not hasattr(chat, 'name') or (hasattr(chat, 'name') and chat.name is None):
                        setattr(chat, 'name', name)
            else:
                chats.add_chat(number + "@s.whatsapp.net", ChatStore(Device.ANDROID, name))


def decode_vcard_value(value: str) -> str:
    """Decode a vCard value that may be quoted-printable UTF-8."""
    try:
        value = value.replace("=\n", "")  # remove soft line breaks
        bytes_val = quopri.decodestring(value)
        return bytes_val.decode("utf-8", errors="replace")
    except Exception:
        return value

def read_vcards_file(vcf_file_path, default_country_code: str):
    contacts = []
    with open(vcf_file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # Split into individual vCards
    vcards = content.split("BEGIN:VCARD")
    for vcard in vcards:
        if "END:VCARD" not in vcard:
            continue

        # Extract name in priority: FN -> N -> ORG
        name = None
        for field in ("FN", "N", "ORG"):
            match = re.search(rf'^{field}(?:;[^:]*)?:(.*)', vcard, re.IGNORECASE | re.MULTILINE)
            if match:
                name = decode_vcard_value(match.group(1).strip())
                break

        if not name:
            continue

        # Extract phone numbers
        numbers = re.findall(r'^\s*TEL(?:;[^:]*)?:(\+?\d+)', vcard, re.IGNORECASE | re.MULTILINE)
        if not numbers:
            continue

        contact = {
            "full_name": name,
            "numbers": numbers,
        }
        contacts.append(contact)

    return map_number_to_name(contacts, default_country_code)


def filter_chats_by_prefix(chats, prefix: str):
    return {k: v for k, v in chats.items() if k.startswith(prefix)}


def map_number_to_name(contacts, default_country_code: str):
    mapping = []
    for contact in contacts:
        for index, num in enumerate(contact['numbers']):
            normalized = normalize_number(num, default_country_code)
            if len(contact['numbers']) > 1:
                name = f"{contact['full_name']} ({index+1})"
            else:
                name = contact['full_name']
            mapping.append((normalized, name))
    return mapping


def normalize_number(number: str, country_code: str):
    # Clean the number
    number = ''.join(c for c in number if c.isdigit() or c == "+")

    # A number that starts with a + or 00 means it already have a country code
    for starting_char in ('+', "00"):
        if number.startswith(starting_char):
            return number[len(starting_char):]

    # leading zero should be removed
    if number.startswith('0'):
        number = number[1:]
    return country_code + number  # fall back
