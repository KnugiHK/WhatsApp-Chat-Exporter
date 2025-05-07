import subprocess
import pytest


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
