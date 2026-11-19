import logging
from types import SimpleNamespace

import pytest

from Whatsapp_Chat_Exporter.__main__ import decrypt_android_backup


@pytest.mark.parametrize(
    "key",
    [
        "0O" + "1" * 62,  # a typo: letter O instead of zero
        "ab" * 31,  # too short
        "a" * 63,  # odd length
    ],
)
def test_invalid_key_is_rejected_without_echoing_it(tmp_path, caplog, capsys, key):
    backup = tmp_path / "msgstore.db.crypt15"
    backup.write_bytes(b"not a real backup")
    args = SimpleNamespace(key=key, backup=str(backup))

    with caplog.at_level(logging.DEBUG):
        try:
            result = decrypt_android_backup(args)
        except Exception as e:  # the key must not leak through an exception either
            result = e

    captured = capsys.readouterr()
    output = caplog.text + captured.out + captured.err + str(result)
    assert result == 1
    assert key not in output
    assert key[2:20] not in output


def _capture_key(monkeypatch):
    seen = {}

    def fake_decrypt_backup(db, key, *args, **kwargs):
        seen["key"] = key.read() if hasattr(key, "read") else key
        return 0

    monkeypatch.setattr(
        "Whatsapp_Chat_Exporter.__main__.android_crypt.decrypt_backup",
        fake_decrypt_backup)
    return seen


def _args(tmp_path, key):
    backup = tmp_path / "msgstore.db.crypt15"
    backup.write_bytes(b"not a real backup")
    return SimpleNamespace(key=key, backup=str(backup), wab=None,
                           db=str(tmp_path / "msgstore.db"), showkey=False,
                           max_bruteforce_worker=1)


def test_hex_key_with_spaces_is_accepted(tmp_path, monkeypatch):
    seen = _capture_key(monkeypatch)
    key = " ".join(["0123456789abcdef"] * 4)

    decrypt_android_backup(_args(tmp_path, key))

    assert seen["key"] == bytes.fromhex(key.replace(" ", ""))


def test_existing_key_file_is_used(tmp_path, monkeypatch):
    seen = _capture_key(monkeypatch)
    key_file = tmp_path / "key"
    key_file.write_bytes(b"key file content")

    decrypt_android_backup(_args(tmp_path, str(key_file)))

    assert seen["key"] == b"key file content"
