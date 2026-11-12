import json
import subprocess
from types import SimpleNamespace

import pytest

from Whatsapp_Chat_Exporter.__main__ import export_json


def test_export_json_writes_relative_path_to_output_directory(tmp_path, monkeypatch):
    """Relative JSON export paths should be resolved against --output."""
    output = tmp_path / "out"
    output.mkdir()
    monkeypatch.chdir(tmp_path)
    args = SimpleNamespace(
        json="result.json",
        output=str(output),
        json_per_chat=False,
        telegram=False,
        avoid_encoding_json=False,
        pretty_print_json=None,
    )

    export_json(args, {})

    assert (output / "result.json").is_file()
    assert not (tmp_path / "result.json").exists()
    assert json.loads((output / "result.json").read_text()) == {}


def test_export_per_chat_json_writes_to_output_directory(tmp_path, monkeypatch):
    """Per-chat JSON exports should also stay inside --output."""
    output = tmp_path / "out"
    output.mkdir()
    monkeypatch.chdir(tmp_path)
    args = SimpleNamespace(
        json="result.json",
        output=str(output),
        json_per_chat=True,
        telegram=False,
        avoid_encoding_json=False,
        pretty_print_json=None,
        timezone_offset=0,
    )

    export_json(args, {"123": {"name": "Alice", "messages": {}}})

    assert (output / "result" / "Alice.json").is_file()
    assert not (tmp_path / "result" / "Alice.json").exists()

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


def test_sanity_check(command_runner):
    """
    This is a basic sanity check to make sure all modules can be imported
    This runs the exporter without any arguments.  It should fail with a 
    message about missing arguments.
    """
    result = command_runner(["wtsexporter"], False)
    expected_stderr = "You must define the device type"
    assert expected_stderr in result.stderr, f"STDERR was: {result.stderr}"
    assert result.returncode == 2


def test_android(command_runner):
    ...


def test_ios(command_runner):
    ...
