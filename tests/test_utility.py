import pytest
import random
import string
from unittest.mock import patch, mock_open, MagicMock
from Whatsapp_Chat_Exporter.utility import *


def test_convert_time_unit():
    assert convert_time_unit(0) == "less than a second"
    assert convert_time_unit(1) == "a second"
    assert convert_time_unit(10) == "10 seconds"
    assert convert_time_unit(60) == "1 minute"
    assert convert_time_unit(61) == "1 minute 1 second"
    assert convert_time_unit(122) == "2 minutes 2 seconds"
    assert convert_time_unit(3600) == "1 hour"
    assert convert_time_unit(3661) == "1 hour 1 minute 1 second"
    assert convert_time_unit(3720) == "1 hour 2 minutes"
    assert convert_time_unit(3660) == "1 hour 1 minute"
    assert convert_time_unit(7263) == "2 hours 1 minute 3 seconds"
    assert convert_time_unit(86400) == "1 day"
    assert convert_time_unit(86461) == "1 day 1 minute 1 second"
    assert convert_time_unit(172805) == "2 days 5 seconds"


class TestBytesToReadable:
    assert bytes_to_readable(0) == "0 B"
    assert bytes_to_readable(500) == "500 B"
    assert bytes_to_readable(1024) == "1.0 KB"
    assert bytes_to_readable(2048) == "2.0 KB"
    assert bytes_to_readable(1536) == "1.5 KB"
    assert bytes_to_readable(1024**2) == "1.0 MB"
    assert bytes_to_readable(5 * 1024**2) == "5.0 MB"
    assert bytes_to_readable(1024**3) == "1.0 GB"
    assert bytes_to_readable(1024**4) == "1.0 TB"
    assert bytes_to_readable(1024**5) == "1.0 PB"
    assert bytes_to_readable(1024**6) == "1.0 EB"
    assert bytes_to_readable(1024**7) == "1.0 ZB"
    assert bytes_to_readable(1024**8) == "1.0 YB"


class TestReadableToBytes:
    def test_conversion(self):
        assert readable_to_bytes("0B") == 0
        assert readable_to_bytes("100B") == 100
        assert readable_to_bytes("50 B") == 50
        assert readable_to_bytes("1KB") == 1024
        assert readable_to_bytes("2.5 KB") == 2560
        assert readable_to_bytes("2.0 KB") == 2048
        assert readable_to_bytes("1MB") == 1024**2
        assert readable_to_bytes("0.5 MB") == 524288
        assert readable_to_bytes("1. MB") == 1048576
        assert readable_to_bytes("1GB") == 1024**3
        assert readable_to_bytes("1.GB") == 1024**3
        assert readable_to_bytes("1TB") == 1024**4
        assert readable_to_bytes("1PB") == 1024**5
        assert readable_to_bytes("1EB") == 1024**6
        assert readable_to_bytes("1ZB") == 1024**7
        assert readable_to_bytes("1YB") == 1024**8

    def test_case_insensitivity(self):
        assert readable_to_bytes("1kb") == 1024
        assert readable_to_bytes("2mB") == 2 * 1024**2

    def test_whitespace(self):
        assert readable_to_bytes(" 10 KB ") == 10 * 1024
        assert readable_to_bytes(" 1 MB") == 1024**2

    def test_invalid_unit(self):
        with pytest.raises(ValueError, match="Invalid size format for size_str"):
            readable_to_bytes("100X")
            readable_to_bytes("A100")
            readable_to_bytes("100$$$$$")

    def test_invalid_number(self):
        with pytest.raises(ValueError, match="Invalid size format for size_str"):
            readable_to_bytes("ABC KB")

    def test_missing_unit(self):
        assert readable_to_bytes("100") == 100


class TestSanitizeExcept:
    def test_no_tags(self):
        html = "This is plain text."
        assert sanitize_except(html) == Markup("This is plain text.")

    def test_allowed_br_tag(self):
        html = "Line 1<br>Line 2"
        assert sanitize_except(html) == Markup("Line 1<br>Line 2")
        html = "<br/>Line"
        assert sanitize_except(html) == Markup("<br>Line")
        html = "Line<br />"
        assert sanitize_except(html) == Markup("Line<br>")

    def test_mixed_tags(self):
        html = "<b>Bold</b><br><i>Italic</i><img src='evil.gif'><script>alert('XSS')</script>"
        assert sanitize_except(html) == Markup(
            "&lt;b&gt;Bold&lt;/b&gt;<br>&lt;i&gt;Italic&lt;/i&gt;&lt;img src='evil.gif'&gt;&lt;script&gt;alert('XSS')&lt;/script&gt;")

    def test_attribute_stripping(self):
        html = "<br class='someclass'>"
        assert sanitize_except(html) == Markup("<br>")


class TestDetermineDay:
    def test_same_day(self):
        timestamp1 = 1678838400  # March 15, 2023 00:00:00 GMT
        timestamp2 = 1678881600  # March 15, 2023 12:00:00 GMT
        assert determine_day(timestamp1, timestamp2) is None

    def test_different_day(self):
        timestamp1 = 1678886400  # March 15, 2023 00:00:00 GMT
        timestamp2 = 1678972800  # March 16, 2023 00:00:00 GMT
        assert determine_day(timestamp1, timestamp2) == datetime(2023, 3, 16).date()

    def test_crossing_month(self):
        timestamp1 = 1680220800  # March 31, 2023 00:00:00 GMT
        timestamp2 = 1680307200  # April 1, 2023 00:00:00 GMT
        assert determine_day(timestamp1, timestamp2) == datetime(2023, 4, 1).date()

    def test_crossing_year(self):
        timestamp1 = 1703980800  # December 31, 2023 00:00:00 GMT
        timestamp2 = 1704067200  # January 1, 2024 00:00:00 GMT
        assert determine_day(timestamp1, timestamp2) == datetime(2024, 1, 1).date()


class TestGetFileName:
    def test_valid_contact_phone_number_no_chat_name(self):
        chat = ChatStore(Device.ANDROID, name=None)
        filename, name = get_file_name("1234567890@s.whatsapp.net", chat)
        assert filename == "1234567890"
        assert name == "1234567890"

    def test_valid_contact_phone_number_with_chat_name(self):
        chat = ChatStore(Device.IOS, name="My Chat Group")
        filename, name = get_file_name("1234567890@s.whatsapp.net", chat)
        assert filename == "1234567890-My-Chat-Group"
        assert name == "My Chat Group"

    def test_valid_contact_exported_chat(self):
        chat = ChatStore(Device.ANDROID, name="Testing")
        filename, name = get_file_name("ExportedChat", chat)
        assert filename == "ExportedChat-Testing"
        assert name == "Testing"

    def test_valid_contact_special_ids(self):
        chat = ChatStore(Device.ANDROID, name="Special Chat")
        filename_000, name_000 = get_file_name("000000000000000", chat)
        assert filename_000 == "000000000000000-Special-Chat"
        assert name_000 == "Special Chat"
        filename_001, name_001 = get_file_name("000000000000001", chat)
        assert filename_001 == "000000000000001-Special-Chat"
        assert name_001 == "Special Chat"

    def test_unexpected_contact_format(self):
        chat = ChatStore(Device.ANDROID, name="Some Chat")
        with pytest.raises(ValueError, match="Unexpected contact format: invalid-contact"):
            get_file_name("invalid-contact", chat)

    def test_contact_with_hyphen_and_chat_name(self):
        chat = ChatStore(Device.ANDROID, name="Another Chat")
        filename, name = get_file_name("123-456-7890@g.us", chat)
        assert filename == "Another-Chat"
        assert name == "Another Chat"

    def test_contact_with_hyphen_no_chat_name(self):
        chat = ChatStore(Device.ANDROID, name=None)
        filename, name = get_file_name("123-456-7890@g.us", chat)
        assert filename == "123-456-7890"
        assert name == "123-456-7890"


class TestGetCondForEmpty:
    def test_enable_true(self):
        condition = get_cond_for_empty(True, "c.jid", "c.broadcast")
        assert condition == "AND (chat.hidden=0 OR c.jid='status@broadcast' OR c.broadcast>0)"

    def test_enable_false(self):
        condition = get_cond_for_empty(False, "other_jid", "other_broadcast")
        assert condition == ""


class TestGetChatCondition:
    ...


class TestGetStatusLocation:
    @patch('os.path.isdir')
    @patch('os.path.isfile')
    @patch('os.mkdir')
    @patch('urllib.request.urlopen')
    @patch('builtins.open', new_callable=mock_open)
    def test_offline_static_set(self, mock_open_file, mock_urlopen, mock_mkdir, mock_isfile, mock_isdir):
        mock_isdir.return_value = False
        mock_isfile.return_value = False
        mock_response = MagicMock()
        mock_response.read.return_value = b'W3.CSS Content'
        mock_urlopen.return_value.__enter__.return_value = mock_response
        output_folder = "output_folder"
        offline_static = "offline_static"

        result = get_status_location(output_folder, offline_static)

        assert result == os.path.join(offline_static, "w3.css")
        mock_mkdir.assert_called_once_with(os.path.join(output_folder, offline_static))
        mock_urlopen.assert_called_once_with("https://www.w3schools.com/w3css/4/w3.css")
        mock_open_file.assert_called_once_with(os.path.join(output_folder, offline_static, "w3.css"), "wb")
        mock_open_file().write.assert_called_once_with(b'W3.CSS Content')

    def test_offline_static_not_set(self):
        result = get_status_location("output_folder", "")
        assert result == "https://www.w3schools.com/w3css/4/w3.css"


class TestSafeName:
    def generate_random_string(length=50):
        random.seed(10)
        return ''.join(random.choice(string.ascii_letters + string.digits + "äöüß") for _ in range(length))

    safe_name_test_cases = [
        ("This is a test string", "This-is-a-test-string"),
        ("This is a test string with special characters!@#$%^&*()",
         "This-is-a-test-string-with-special-characters"),
        ("This is a test string with numbers 1234567890", "This-is-a-test-string-with-numbers-1234567890"),
        ("This is a test string with mixed case ThisIsATestString",
         "This-is-a-test-string-with-mixed-case-ThisIsATestString"),
        ("This is a test string with extra spaces \u00A0 \u00A0 \u00A0 ThisIsATestString",
         "This-is-a-test-string-with-extra-spaces-ThisIsATestString"),
        ("This is a test string with unicode characters äöüß",
         "This-is-a-test-string-with-unicode-characters-äöüß"),
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
        ("test.com/path/to/resource?param1=value1&param2=value2",
         "test.compathtoresourceparam1value1param2value2"),  # Test with URL
        ("filename.txt", "filename.txt"),  # Test with filename
        ("Αυτή είναι μια δοκιμαστική συμβολοσειρά με ελληνικούς χαρακτήρες.",
         "Αυτή-είναι-μια-δοκιμαστική-συμβολοσειρά-με-ελληνικούς-χαρακτήρες."),  # Greek characters
        ("This is a test with комбинированные знаки ̆ example",
         "This-is-a-test-with-комбинированные-знаки-example")  # Mixed with unicode
    ]

    @pytest.mark.parametrize("input_text, expected_output", safe_name_test_cases)
    def test_safe_name(self, input_text, expected_output):
        result = safe_name(input_text)
        assert result == expected_output
