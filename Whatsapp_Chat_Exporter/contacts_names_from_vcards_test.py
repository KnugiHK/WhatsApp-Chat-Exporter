# from contacts_names_from_vcards import readVCardsFile

from Whatsapp_Chat_Exporter.contacts_names_from_vcards import normalize_number, readVCardsFile


def test_readVCardsFile():
    l = readVCardsFile("contacts.vcf", "973")
    
    assert len(l) > 0

def test_createNumberToNameDicts():
    pass

def test_fuzzy_match_numbers():
    pass

def test_normalize_number():
    assert normalize_number('0531234567', '1') == '1531234567'
    assert normalize_number('001531234567', '2') == '1531234567'
    assert normalize_number('+1531234567', '34') == '1531234567'
    assert normalize_number('053(123)4567', '34') == '34531234567'
    assert normalize_number('0531-234-567', '58') == '58531234567'
