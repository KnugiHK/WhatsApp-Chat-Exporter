import vobject
from typing import List, TypedDict


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

            for chat in filter_chats_by_prefix(chats, number).values():
                if not hasattr(chat, 'name') or (hasattr(chat, 'name') and chat.name is None):
                    setattr(chat, 'name', name)


def read_vcards_file(vcf_file_path, default_country_code: str):
    contacts = []
    with open(vcf_file_path, mode="r", encoding="utf-8") as f:
        reader = vobject.readComponents(f)
        for row in reader:
            if hasattr(row, 'fn'):
                name = str(row.fn.value)
            elif hasattr(row, 'n'):
                name = str(row.n.value)
            else:
                name = None
            if not hasattr(row, 'tel') or name is None:
                continue
            contact: ExportedContactNumbers = {
                "full_name": name,
                "numbers": list(map(lambda tel: tel.value, row.tel_list)),
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
    if starting_char == '0':
        number = number[1:]
    return country_code + number  # fall back
