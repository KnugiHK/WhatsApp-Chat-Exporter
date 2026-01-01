import os
import sys
import pytest
import subprocess


@pytest.fixture
def command_runner():
    """
    A pytest fixture to simplify running commands.  This is a helper
    function that you can use in multiple tests.
    """
    def _run_command(command_list, check=True):
        """
        Runs a command and returns the result.

        Args:
            command_list (list): A list of strings representing the command
                and its arguments (e.g., ["python", "my_script.py", "arg1"]).
            check (bool, optional):  If True, raise an exception if the
                command returns a non-zero exit code.  Defaults to True.

        Returns:
            subprocess.CompletedProcess: The result of the command.
        """
        return subprocess.run(
            command_list,
            capture_output=True,
            text=True,
            check=check,
        )
    return _run_command


def test_nuitka_binary():
    """
    Tests the creation and execution of a Nuitka-compiled binary.
    """

    if sys.version_info >= (3, 14):
        print("Skipping Nuitka test: Python 3.14 is not yet fully supported by Nuitka.")
        return
    
    nuitka_command = [
        "python", "-m", "nuitka", "--onefile", "--assume-yes-for-downloads",
        "--include-data-file=./Whatsapp_Chat_Exporter/whatsapp.html=./Whatsapp_Chat_Exporter/whatsapp.html",
        "Whatsapp_Chat_Exporter",
        "--output-filename=wtsexporter.exe"  # use .exe on all platforms for compatibility
    ]

    compile_result = subprocess.run(
        nuitka_command,
        capture_output=True,
        text=True,
        check=True
    )
    print(f"Nuitka compilation output: {compile_result.stdout}")

    binary_path = "./wtsexporter.exe"
    assert os.path.exists(binary_path), f"Binary {binary_path} was not created."

    try:
        execute_result = subprocess.run(
            [binary_path, "--help"],
            capture_output=True,
            text=True,
            check=True,
        )
        print(f"Binary execution output: {execute_result.stdout}")
        assert "usage:" in execute_result.stdout.lower(), "Binary did not produce expected help output."
    except subprocess.CalledProcessError as e:
        print(f"Binary execution failed with error: {e.stderr}")
        raise
    finally:
        if os.path.exists(binary_path):
            os.remove(binary_path)
