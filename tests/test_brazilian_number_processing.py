import subprocess
import unittest
import tempfile
import os
from unittest.mock import patch

from scripts.brazilian_number_processing import process_phone_number, process_vcard


class TestVCardProcessor(unittest.TestCase):

    def test_process_phone_number(self):
        """Test the process_phone_number function with various inputs."""

        # Test cases for 9-digit subscriber numbers
        test_cases_9_digit = [
            # Standard 11-digit number (2 area + 9 subscriber)
            ("27912345678", "+55 27 91234-5678", "+55 27 1234-5678"),
            # With country code prefix
            ("5527912345678", "+55 27 91234-5678", "+55 27 1234-5678"),
            # With plus in country code
            ("+5527912345678", "+55 27 91234-5678", "+55 27 1234-5678"),
            # With spaces and formatting
            ("+55 27 9 1234-5678", "+55 27 91234-5678", "+55 27 1234-5678"),
            # With trunk zero
            ("027912345678", "+55 27 91234-5678", "+55 27 1234-5678"),
            # With country code and trunk zero
            ("+55027912345678", "+55 27 91234-5678", "+55 27 1234-5678"),
            # With extra digits at the beginning (should use last 11)
            ("99927912345678", "+55 27 91234-5678", "+55 27 1234-5678"),
            # With extra non-digit characters
            ("+55-27-9.1234_5678", "+55 27 91234-5678", "+55 27 1234-5678"),
        ]

        # Test cases for 8-digit subscriber numbers
        test_cases_8_digit = [
            # Standard 10-digit number (2 area + 8 subscriber)
            ("2712345678", "+55 27 1234-5678", None),
            # With country code prefix
            ("552712345678", "+55 27 1234-5678", None),
            # With plus in country code
            ("+552712345678", "+55 27 1234-5678", None),
            # With spaces and formatting
            ("+55 27 1234-5678", "+55 27 1234-5678", None),
            # With trunk zero
            ("02712345678", "+55 27 1234-5678", None),
            # With country code and trunk zero
            ("+55 0 27 1234-5678", "+55 27 1234-5678", None),
        ]

        # Edge cases
        edge_cases = [
            # Too few digits
            ("271234567", None, None),
            # Empty string
            ("", None, None),
            # Non-numeric characters only
            ("abc-def+ghi", None, None),
            # Single digit
            ("1", None, None),
            # Unusual formatting but valid number
            ("(+55) [27] 9.1234_5678", "+55 27 91234-5678", "+55 27 1234-5678"),
        ]

        # Run tests for all cases
        all_cases = test_cases_9_digit + test_cases_8_digit + edge_cases

        for raw_phone, expected_orig, expected_mod in all_cases:
            with self.subTest(raw_phone=raw_phone):
                orig, mod = process_phone_number(raw_phone)
                self.assertEqual(orig, expected_orig)
                self.assertEqual(mod, expected_mod)

    def test_process_vcard(self):
        """Test the process_vcard function with various VCARD formats."""

        # Test case 1: Standard TEL entries
        vcard1 = """BEGIN:VCARD
VERSION:3.0
N:Doe;John;;;
FN:John Doe
TEL:+5527912345678
TEL:+552712345678
END:VCARD
"""
        expected1 = """BEGIN:VCARD
VERSION:3.0
N:Doe;John;;;
FN:John Doe
TEL;TYPE=CELL:+55 27 91234-5678
TEL;TYPE=CELL:+55 27 1234-5678
TEL;TYPE=CELL:+55 27 1234-5678
END:VCARD
"""

        # Test case 2: TEL entries with TYPE attributes
        vcard2 = """BEGIN:VCARD
VERSION:3.0
N:Smith;Jane;;;
FN:Jane Smith
TEL;TYPE=CELL:+5527912345678
TEL;TYPE=HOME:+552712345678
END:VCARD
"""
        expected2 = """BEGIN:VCARD
VERSION:3.0
N:Smith;Jane;;;
FN:Jane Smith
TEL;TYPE=CELL:+55 27 91234-5678
TEL;TYPE=CELL:+55 27 1234-5678
TEL;TYPE=CELL:+55 27 1234-5678
END:VCARD
"""

        # Test case 3: Complex TEL entries with prefixes
        vcard3 = """BEGIN:VCARD
VERSION:3.0
N:Brown;Robert;;;
FN:Robert Brown
item1.TEL:+5527912345678
item2.TEL;TYPE=CELL:+552712345678
END:VCARD
"""
        expected3 = """BEGIN:VCARD
VERSION:3.0
N:Brown;Robert;;;
FN:Robert Brown
TEL;TYPE=CELL:+55 27 91234-5678
TEL;TYPE=CELL:+55 27 1234-5678
TEL;TYPE=CELL:+55 27 1234-5678
END:VCARD
"""

        # Test case 4: Mixed valid and invalid phone numbers
        vcard4 = """BEGIN:VCARD
VERSION:3.0
N:White;Alice;;;
FN:Alice White
TEL:123
TEL:+5527912345678
END:VCARD
"""
        expected4 = """BEGIN:VCARD
VERSION:3.0
N:White;Alice;;;
FN:Alice White
TEL:123
TEL;TYPE=CELL:+55 27 91234-5678
TEL;TYPE=CELL:+55 27 1234-5678
END:VCARD
"""

        # Test case 5: Multiple contacts with different formats
        vcard5 = """BEGIN:VCARD
VERSION:3.0
N:Johnson;Mike;;;
FN:Mike Johnson
TEL:27912345678
END:VCARD
BEGIN:VCARD
VERSION:3.0
N:Williams;Sarah;;;
FN:Sarah Williams
TEL;TYPE=CELL:2712345678
END:VCARD
"""
        expected5 = """BEGIN:VCARD
VERSION:3.0
N:Johnson;Mike;;;
FN:Mike Johnson
TEL;TYPE=CELL:+55 27 91234-5678
TEL;TYPE=CELL:+55 27 1234-5678
END:VCARD
BEGIN:VCARD
VERSION:3.0
N:Williams;Sarah;;;
FN:Sarah Williams
TEL;TYPE=CELL:+55 27 1234-5678
END:VCARD
"""

        # Test case 6: VCARD with no phone numbers
        vcard6 = """BEGIN:VCARD
VERSION:3.0
N:Davis;Tom;;;
FN:Tom Davis
EMAIL:tom@example.com
END:VCARD
"""
        expected6 = """BEGIN:VCARD
VERSION:3.0
N:Davis;Tom;;;
FN:Tom Davis
EMAIL:tom@example.com
END:VCARD
"""

        test_cases = [
            (vcard1, expected1),
            (vcard2, expected2),
            (vcard3, expected3),
            (vcard4, expected4),
            (vcard5, expected5),
            (vcard6, expected6)
        ]

        for i, (input_vcard, expected_output) in enumerate(test_cases):
            with self.subTest(case=i+1):
                # Create temporary files for input and output
                with tempfile.NamedTemporaryFile(mode='w+', delete=False, encoding='utf-8') as input_file:
                    input_file.write(input_vcard)
                    input_path = input_file.name

                output_path = input_path + '.out'

                try:
                    # Process the VCARD
                    process_vcard(input_path, output_path)

                    # Read and verify the output
                    with open(output_path, 'r', encoding='utf-8') as output_file:
                        actual_output = output_file.read()

                    self.assertEqual(actual_output, expected_output)

                finally:
                    # Clean up temporary files
                    if os.path.exists(input_path):
                        os.unlink(input_path)
                    if os.path.exists(output_path):
                        os.unlink(output_path)

    def test_script_argument_handling(self):
        """Test the script's command-line argument handling."""

        test_input = """BEGIN:VCARD
VERSION:3.0
N:Test;User;;;
FN:User Test
TEL:+5527912345678
END:VCARD
"""

        # Create a temporary input file
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, encoding='utf-8') as input_file:
            input_file.write(test_input)
            input_path = input_file.name

        output_path = input_path + '.out'

        try:
            test_args = ['python' if os.name == 'nt' else 'python3',
                         'scripts/brazilian_number_processing.py', input_path, output_path]
            # We're just testing that the argument parsing works
            subprocess.call(
                test_args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT
            )
            # Check if the output file was created
            self.assertTrue(os.path.exists(output_path))

        finally:
            # Clean up temporary files
            if os.path.exists(input_path):
                os.unlink(input_path)
            if os.path.exists(output_path):
                os.unlink(output_path)


if __name__ == '__main__':
    unittest.main()
