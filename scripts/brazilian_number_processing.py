"""
This script processes a VCARD file to standardize telephone entries and add a second TEL line with the modified number (removing the extra ninth digit) for contacts with 9-digit subscribers.
It handles numbers that may already include a "+55" prefix and ensures that the output format is consistent.
Contributed by @magpires https://github.com/KnugiHK/WhatsApp-Chat-Exporter/issues/127#issuecomment-2646660625
"""
import re
import argparse

def process_phone_number(raw_phone):
    """
    Process the raw phone string from the VCARD and return two formatted numbers:
      - The original formatted number, and
      - A modified formatted number with the extra (ninth) digit removed, if applicable.
      
    Desired output:
      For a number with a 9-digit subscriber:
         Original: "+55 {area} {first 5 of subscriber}-{last 4 of subscriber}"
         Modified: "+55 {area} {subscriber[1:5]}-{subscriber[5:]}" 
      For example, for an input that should represent "027912345678", the outputs are:
         "+55 27 91234-5678"  and  "+55 27 1234-5678"
    
    This function handles numbers that may already include a "+55" prefix.
    It expects that after cleaning, a valid number (without the country code) should have either 10 digits 
    (2 for area + 8 for subscriber) or 11 digits (2 for area + 9 for subscriber).
    If extra digits are present, it takes the last 11 (or 10) digits.
    """
    # Store the original input for processing
    number_to_process = raw_phone.strip()
    
    # Remove all non-digit characters
    digits = re.sub(r'\D', '', number_to_process)
    
    # If the number starts with '55', remove it for processing
    if digits.startswith("55") and len(digits) > 11:
        digits = digits[2:]
    
    # Remove trunk zero if present
    if digits.startswith("0"):
        digits = digits[1:]
    
    # After cleaning, we expect a valid number to have either 10 or 11 digits
    # If there are extra digits, use the last 11 (for a 9-digit subscriber) or last 10 (for an 8-digit subscriber)
    if len(digits) > 11:
        # Here, we assume the valid number is the last 11 digits
        digits = digits[-11:]
    elif len(digits) > 10 and len(digits) < 11:
        # In some cases with an 8-digit subscriber, take the last 10 digits
        digits = digits[-10:]
    
    # Check if we have a valid number after processing
    if len(digits) not in (10, 11):
        return None, None

    area = digits[:2]
    subscriber = digits[2:]

    if len(subscriber) == 9:
        # Format the original number (5-4 split, e.g., "91234-5678")
        orig_subscriber = f"{subscriber[:5]}-{subscriber[5:]}"
        # Create a modified version: drop the first digit of the subscriber to form an 8-digit subscriber (4-4 split)
        mod_subscriber = f"{subscriber[1:5]}-{subscriber[5:]}"
        original_formatted = f"+55 {area} {orig_subscriber}"
        modified_formatted = f"+55 {area} {mod_subscriber}"
    elif len(subscriber) == 8:
        original_formatted = f"+55 {area} {subscriber[:4]}-{subscriber[4:]}"
        modified_formatted = None
    else:
        # This shouldn't happen given the earlier check, but just to be safe
        return None, None

    return original_formatted, modified_formatted

def process_vcard(input_vcard, output_vcard):
    """
    Process a VCARD file to standardize telephone entries and add a second TEL line
    with the modified number (removing the extra ninth digit) for contacts with 9-digit subscribers.
    """
    with open(input_vcard, 'r', encoding='utf-8') as file:
        lines = file.readlines()
    
    output_lines = []
    
    # Regex to capture any telephone line.
    # It matches lines starting with "TEL:" or "TEL;TYPE=..." or with prefixes like "item1.TEL:".
    phone_pattern = re.compile(r'^(?P<prefix>.*TEL(?:;TYPE=[^:]+)?):(?P<number>.*)$')
    
    for line in lines:
        stripped_line = line.rstrip("\n")
        match = phone_pattern.match(stripped_line)
        if match:
            raw_phone = match.group("number").strip()
            orig_formatted, mod_formatted = process_phone_number(raw_phone)
            if orig_formatted:
                # Always output using the standardized prefix.
                output_lines.append(f"TEL;TYPE=CELL:{orig_formatted}\n")
            else:
                output_lines.append(line)
            if mod_formatted:
                output_lines.append(f"TEL;TYPE=CELL:{mod_formatted}\n")
        else:
            output_lines.append(line)
    
    with open(output_vcard, 'w', encoding='utf-8') as file:
        file.writelines(output_lines)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Process a VCARD file to standardize telephone entries and add a second TEL line with the modified number (removing the extra ninth digit) for contacts with 9-digit subscribers."
    )
    parser.add_argument('input_vcard', type=str, help='Input VCARD file')
    parser.add_argument('output_vcard', type=str, help='Output VCARD file')
    args = parser.parse_args()
    
    process_vcard(args.input_vcard, args.output_vcard)
    print(f"VCARD processed and saved to {args.output_vcard}")