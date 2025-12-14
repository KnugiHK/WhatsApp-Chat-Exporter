import logging
import re
import quopri
from typing import List, TypedDict
from Whatsapp_Chat_Exporter.data_model import ChatStore
from Whatsapp_Chat_Exporter.utility import CLEAR_LINE, Device


logger = logging.getLogger(__name__)


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


def decode_quoted_printable(value: str, charset: str) -> str:
    """Decode a vCard value that may be quoted-printable UTF-8."""
    try:
        bytes_val = quopri.decodestring(value)
        return bytes_val.decode(charset, errors="replace")
    except Exception:
        # Fallback: return the original value if decoding fails
        logger.warning(
            f"Failed to decode quoted-printable value: {value}, "
            f"charset: {charset}. Please report this issue.{CLEAR_LINE}"
        )
        return value

def _parse_vcard_line(line: str) -> tuple[str, dict[str, str], str] | None:
    """
    Parses a single vCard property line into its components:
    Property Name, Parameters (as a dict), and Value.
    
    Example: 'FN;CHARSET=UTF-8:John Doe' -> ('FN', {'CHARSET': 'UTF-8'}, 'John Doe')
    """
    # Find the first colon, which separates the property/parameters from the value.
    colon_index = line.find(':')
    if colon_index == -1:
        return None # Invalid vCard line format

    prop_and_params = line[:colon_index].strip()
    value = line[colon_index + 1:].strip()

    # Split property name from parameters
    parts = prop_and_params.split(';')
    property_name = parts[0].upper()
    
    parameters = {}
    for part in parts[1:]:
        if '=' in part:
            key, val = part.split('=', 1)
            parameters[key.upper()] = val.strip('"') # Remove potential quotes from value

    return property_name, parameters, value


def get_vcard_value(entry: str, field_name: str) -> list[str]:
    """
    Scans the vCard entry for lines starting with the specific field_name 
    and returns a list of its decoded values, handling parameters like
    ENCODING and CHARSET.
    """
    target_name = field_name.upper()
    cached_line = ""
    charset = "utf-8"
    values = []
    
    for line in entry.splitlines():
        line = line.strip()
        if cached_line:
            if line.endswith('='):
                cached_line += line[:-1]
                continue  # Wait for the next line to complete the value
            values.append(decode_quoted_printable(cached_line + line, charset))
            cached_line = ""
        else:
            # Skip empty lines or lines that don't start with the target field (after stripping)
            if not line or not line.upper().startswith(target_name):
                continue

            parsed = _parse_vcard_line(line)
            if parsed is None:
                continue

            prop_name, params, raw_value = parsed

            if prop_name != target_name:
                continue

            encoding = params.get('ENCODING')
            charset = params.get('CHARSET', 'utf-8')

            # Apply decoding if ENCODING parameter is present
            if encoding == 'QUOTED-PRINTABLE':
                if raw_value.endswith('='):
                    # Handle soft line breaks in quoted-printable and cache the line
                    cached_line += raw_value[:-1]
                    continue  # Wait for the next line to complete the value
                values.append(decode_quoted_printable(raw_value, charset))
            elif encoding:
                raise NotImplementedError(f"Encoding '{encoding}' not supported yet.")
            else:
                values.append(raw_value)
    return values


def process_vcard_entry(entry: str) -> dict | bool:
    """
    Process a vCard entry using pure string manipulation
    
    Args:
        entry: A string containing a single vCard block.
        
    Returns:
        A dictionary of the extracted data or False if required fields are missing.
    """
    
    name = None
    
    # Extract name in priority: FN -> N -> ORG
    for field in ("FN", "N", "ORG"):
        if name_values := get_vcard_value(entry, field):
            name = name_values[0].replace(';', ' ') # Simple cleanup for structured name
            break

    if not name:
        return False

    numbers = get_vcard_value(entry, "TEL")
    if not numbers:
        return False

    return {
        "full_name": name,
        # Remove duplications
        "numbers": set(numbers),
    }


def read_vcards_file(vcf_file_path, default_country_code: str):
    contacts = []
    with open(vcf_file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # Split into individual vCards
    vcards = content.split("BEGIN:VCARD")
    for vcard in vcards:
        if "END:VCARD" not in vcard:
            continue

        if contact := process_vcard_entry(vcard):
            contacts.append(contact)

    logger.info(f"Imported {len(contacts)} contacts/vcards{CLEAR_LINE}")
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
