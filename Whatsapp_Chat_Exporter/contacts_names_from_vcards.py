import itertools
from typing import List, TypedDict

try:
    import vobject
except ModuleNotFoundError:
    vcards_deps_installed = False
else:
    vcards_deps_installed = True

class ContactsNamesFromVCards:
    def __init__(self) -> None:
        self.l = []
        
    def should_enrich_names_from_vCards(self):
        return len(self.l) > 0
    
    def load_vcf_file(self, vcfFilePath: str, default_country_calling_code: str):
        if not vcards_deps_installed:
            raise Exception('Invariant: vobject is missing')
        self.l = readVCardsFile(vcfFilePath, default_country_calling_code)
    
    def enrich_names_from_vCards(self, chats):
        for counter, (number, name) in enumerate(self.l):
            # short number must be a bad contact, lets skip it
            if len(number) <= 5:
                continue

            for counter, chat in enumerate(filter_dict_by_prefix(chats, number).values()):
                if not hasattr(chat, 'name') or (hasattr(chat, 'name') and chat.name is None):
                    setattr(chat, 'name', name)


def readVCardsFile(vcfFilePath, default_country_calling_code: str):
    contacts = []
    with open(vcfFilePath, mode="r") as f:
        reader = vobject.readComponents(f)
        for row in reader:
            if not hasattr(row, 'fn'):
                continue
            
            if not hasattr(row, 'tel'):
                continue
            
            contact: ExportedGoogleContactVCARDRawNumbers = {
                "full_name": row.fn.value,
                "numbers": list(map(lambda tel:tel.value, row.tel_list)),
            }

            contacts.append(contact)

    step2 = createNumberToNameDicts(contacts, default_country_calling_code)

    return step2

    
def filter_dict_by_prefix(d, prefix: str):
    return {k: v for k, v in d.items() if k.startswith(prefix)}

def createNumberToNameDicts(inContacts, default_country_calling_code: str):
    outContacts = list(itertools.chain.from_iterable(
        [[normalize_number(num, default_country_calling_code), f"{contact['full_name']} ({i+1})" if len(contact['numbers']) > 1 else contact['full_name']] 
        for i, num in enumerate(contact['numbers'])] 
        for contact in inContacts
    ))

    return outContacts
        
class ExportedGoogleContactVCARDRawNumbers(TypedDict):
    full_name: str
    numbers: List[str]
    
def normalize_number(number: str, default_country_calling_code: str):
    afterSomeCleaning = number.replace('(', '').replace(')', '').replace(' ', '').replace('-', '')

    # A number that starts with a + or 00 means it already have country_calling_code
    if afterSomeCleaning.startswith('+'):
        afterSomeCleaning = afterSomeCleaning.replace('+', '')
    elif afterSomeCleaning.startswith('00'):
        afterSomeCleaning = afterSomeCleaning[2:]
    else:
        # Remove leading zero
        if afterSomeCleaning.startswith('0'):
            afterSomeCleaning = afterSomeCleaning[1:]

        afterSomeCleaning = default_country_calling_code + afterSomeCleaning
        
    return afterSomeCleaning