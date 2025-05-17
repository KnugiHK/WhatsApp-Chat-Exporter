import pytest
import random
import string

from Whatsapp_Chat_Exporter.utility import safe_name

def generate_random_string(length=50):
    random.seed(10)
    return ''.join(random.choice(string.ascii_letters + string.digits + "äöüß") for _ in range(length))


# Test cases to validate the safe_name function
safe_name_test_cases = [
    ("This is a test string", "This-is-a-test-string"),
    ("This is a test string with special characters!@#$%^&*()", "This-is-a-test-string-with-special-characters"),
    ("This is a test string with numbers 1234567890", "This-is-a-test-string-with-numbers-1234567890"),
    ("This is a test string with mixed case ThisIsATestString", "This-is-a-test-string-with-mixed-case-ThisIsATestString"),
    ("This is a test string with extra spaces     ThisIsATestString", "This-is-a-test-string-with-extra-spaces-ThisIsATestString"),
    ("This is a test string with unicode characters äöüß", "This-is-a-test-string-with-unicode-characters-äöüß"),
    ("這是一個包含中文的測試字符串", "這是一個包含中文的測試字符串"),  # Chinese characters, should stay as is
    (
        f"This is a test string with long length {generate_random_string(1000)}",
        f"This-is-a-test-string-with-long-length-{generate_random_string(1000)}",
    ),
    ("", ""),  # Empty string
    (" ", ""),  # String with only space
    ("---", "---"),  # String with only hyphens
    ("___", "___"),  # String with only underscores
    ("a" * 100, "a" * 100),  # Long string with single character
    ("a-b-c-d-e", "a-b-c-d-e"),  # String with hyphen
    ("a_b_c_d_e", "a_b_c_d_e"),  # String with underscore
    ("a b c d e", "a-b-c-d-e"),  # String with spaces
    ("test.com/path/to/resource?param1=value1&param2=value2", "test.compathtoresourceparam1value1param2value2"),  # Test with URL
    ("filename.txt", "filename.txt"),  # Test with filename
    ("Αυτή είναι μια δοκιμαστική συμβολοσειρά με ελληνικούς χαρακτήρες.", "Αυτή-είναι-μια-δοκιμαστική-συμβολοσειρά-με-ελληνικούς-χαρακτήρες."),  # Greek characters
    ("This is a test with комбинированные знаки ̆ example", "This-is-a-test-with-комбинированные-знаки-example")  # Mixed with unicode
]


@pytest.mark.parametrize("input_text, expected_output", safe_name_test_cases)
def test_safe_name(input_text, expected_output):
    result = safe_name(input_text)
    assert result == expected_output