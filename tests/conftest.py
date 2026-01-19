import pytest
import os

def pytest_collection_modifyitems(config, items):
    """
    Moves test_nuitka_binary.py to the end and fails if the file is missing.
    """
    target_file = "test_nuitka_binary.py"
    
    # Sanity Check: Ensure the file actually exists in the tests directory
    test_dir = os.path.join(config.rootdir, "tests")
    file_path = os.path.join(test_dir, target_file)
    
    if not os.path.exists(file_path):
        pytest.exit(f"\n[FATAL] Required test file '{target_file}' not found in {test_dir}. "
                    f"Order enforcement failed!", returncode=1)

    nuitka_tests = []
    remaining_tests = []

    for item in items:
        if target_file in item.nodeid:
            nuitka_tests.append(item)
        else:
            remaining_tests.append(item)

    items[:] = remaining_tests + nuitka_tests