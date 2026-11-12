import base64
import hashlib
import hmac
import struct

import pytest

AES = pytest.importorskip("Crypto.Cipher.AES")
lzfse = pytest.importorskip("lzfse")

from Whatsapp_Chat_Exporter import ios_crypt
from Whatsapp_Chat_Exporter.android_crypt import InvalidFileFormatError, InvalidKeyError

KEY = bytes(range(32))
IV = bytes(range(16))
PLAINTEXT = b"SQLite format 3\x00" + b"backup data " * 200


def encrypt(plaintext, flags, key=KEY):
    padding = 16 - len(plaintext) % 16
    padded = plaintext + bytes([padding]) * padding
    ciphertext = AES.new(ios_crypt._hkdf(key, b"file"), AES.MODE_CBC, IV).encrypt(padded)
    body = bytes([flags, 1]) + IV + ciphertext
    return body + hmac.new(ios_crypt._hkdf(key, b"file-verify"), body, hashlib.sha256).digest()


def pbze(*blocks):
    return b"pbze" + struct.pack(">Q", 1 << 20) + b"".join(
        struct.pack(">QQ", raw, len(data)) + data for raw, data in blocks
    )


def test_hkdf_counter_starts_at_zero():
    prk = hmac.new(b"\x00" * 32, KEY, hashlib.sha256).digest()
    expected = hmac.new(prk, b"file\x00", hashlib.sha256).digest()
    assert ios_crypt._hkdf(KEY, b"file") == expected


def test_decrypt_uncompressed():
    assert ios_crypt.decrypt_file(encrypt(PLAINTEXT, 0x03), KEY) == PLAINTEXT


def test_decrypt_compressed_lzfse_and_stored_blocks():
    stream = pbze((len(PLAINTEXT), lzfse.compress(PLAINTEXT)), (5, b"tail!"))
    assert ios_crypt.decrypt_file(encrypt(stream, 0x83), KEY) == PLAINTEXT + b"tail!"


def test_wrong_key_rejected():
    with pytest.raises(InvalidKeyError):
        ios_crypt.decrypt_file(encrypt(PLAINTEXT, 0x03), bytes(32))


def test_tampered_file_rejected():
    data = bytearray(encrypt(PLAINTEXT, 0x03))
    data[30] ^= 1
    with pytest.raises(InvalidKeyError):
        ios_crypt.decrypt_file(bytes(data), KEY)


@pytest.mark.parametrize("flags", [0x81, 0x01])
def test_regular_backup_is_reported(flags):
    with pytest.raises(InvalidFileFormatError, match="regular WhatsApp backup"):
        ios_crypt.decrypt_file(encrypt(PLAINTEXT, flags), KEY)


def test_unknown_key_type_rejected():
    with pytest.raises(InvalidFileFormatError, match="Unsupported file type"):
        ios_crypt.decrypt_file(encrypt(PLAINTEXT, 0x84), KEY)


def test_parse_key_from_hex_and_file(tmp_path):
    key_file = tmp_path / "key.txt"
    key_file.write_text(KEY.hex() + "\n")
    assert ios_crypt.parse_key(KEY.hex()) == KEY
    assert ios_crypt.parse_key(str(key_file)) == KEY


def test_parse_key_rejects_bad_value():
    with pytest.raises(InvalidKeyError):
        ios_crypt.parse_key("not a key")


def tar_entry(path, content, tar_key, entry_type=b"W", link=None):
    salt = bytes(range(32, 64))
    derived = ios_crypt._hkdf(tar_key, b"\x00", 80, salt)
    encoded = path.encode()
    header_bytes = bytes([1, 1 if link else 0]) + struct.pack(">Q", 1700000000000) + bytes([len(encoded)]) + encoded
    body = link.encode() if link else struct.pack(">Q", len(content)) + content
    plaintext = header_bytes + body
    padding = 16 - len(plaintext) % 16
    padded = plaintext + bytes([padding]) * padding
    ciphertext = AES.new(derived[:32], AES.MODE_CBC, derived[64:]).encrypt(padded)
    data = ciphertext + hmac.new(derived[32:64], derived[64:] + ciphertext, hashlib.sha256).digest()
    name = base64.urlsafe_b64encode(salt)
    header = bytearray(512)
    header[:len(name)] = name
    header[124:136] = b"%011o\x00" % len(data)
    header[148:156] = b" " * 8
    header[156:157] = entry_type
    header[257:263] = b"ustar\x00"
    header[148:156] = b"%06o\x00 " % sum(header)
    return name, data, bytes(header) + data + bytes((512 - len(data) % 512) % 512)


def test_decrypt_tar_entry():
    tar_key = ios_crypt._hkdf(KEY, b"tar")
    name, data, _ = tar_entry("/Media/1/a.jpg", b"\xff\xd8\xffimage", tar_key)
    assert ios_crypt.decrypt_tar_entry(name, data, tar_key) == ("/Media/1/a.jpg", b"\xff\xd8\xffimage", False)


def test_extract_media_resolves_links(tmp_path):
    tar_key = ios_crypt._hkdf(KEY, b"tar")
    backup = tmp_path / "backup"
    backup.mkdir()
    link = tar_entry("/Media/2/copy.pdf", b"", tar_key, link="Media/1/a.pdf")[2]
    target = tar_entry("/Media/1/a.pdf", b"pdf data", tar_key)[2]
    (backup / "Document.tar").write_bytes(link + target + bytes(1024) + bytes(33))
    media = tmp_path / "media"
    ios_crypt.extract_e2e_media(str(backup), KEY, str(media))
    assert (media / "Message" / "Media" / "2" / "copy.pdf").read_bytes() == b"pdf data"


def test_extract_media_rejects_link_outside_media(tmp_path):
    tar_key = ios_crypt._hkdf(KEY, b"tar")
    backup = tmp_path / "backup"
    backup.mkdir()
    (backup / "Media.tar").write_bytes(tar_entry("/Media/x", b"", tar_key, link="../../../etc/passwd")[2] + bytes(1024))
    with pytest.raises(InvalidFileFormatError):
        ios_crypt.extract_e2e_media(str(backup), KEY, str(tmp_path / "media"))


def test_decrypt_tar_entry_wrong_key():
    tar_key = ios_crypt._hkdf(KEY, b"tar")
    name, data, _ = tar_entry("/Media/1/a.jpg", b"image", tar_key)
    with pytest.raises(InvalidKeyError):
        ios_crypt.decrypt_tar_entry(name, data, bytes(32))


def test_extract_media_writes_files_and_skips_plain_entries(tmp_path):
    tar_key = ios_crypt._hkdf(KEY, b"tar")
    backup = tmp_path / "backup"
    backup.mkdir()
    encrypted = tar_entry("/Media/1/a.jpg", b"image", tar_key)[2]
    plain = tar_entry("/Media/1/plain.jpg", b"plain", tar_key, b"0")[2]
    (backup / "Media.tar").write_bytes(encrypted + plain + bytes(1024) + bytes(33))
    media = tmp_path / "media"
    ios_crypt.extract_e2e_media(str(backup), KEY, str(media))
    assert (media / "Message" / "Media" / "1" / "a.jpg").read_bytes() == b"image"
    assert not (media / "Message" / "Media" / "1" / "plain.jpg").exists()


def test_extract_media_rejects_path_traversal(tmp_path):
    tar_key = ios_crypt._hkdf(KEY, b"tar")
    backup = tmp_path / "backup"
    backup.mkdir()
    (backup / "Media.tar").write_bytes(tar_entry("../../evil.txt", b"x", tar_key)[2] + bytes(1024))
    with pytest.raises(InvalidFileFormatError):
        ios_crypt.extract_e2e_media(str(backup), KEY, str(tmp_path / "media"))
    assert not (tmp_path / "evil.txt").exists()


def test_decrypt_backup_writes_databases(tmp_path, monkeypatch):
    backup = tmp_path / "backup"
    backup.mkdir()
    (backup / ios_crypt.MESSAGE_FILE).write_bytes(encrypt(PLAINTEXT, 0x03))
    (backup / ios_crypt.CALL_FILE).write_bytes(encrypt(b"calls", 0x03))
    monkeypatch.chdir(tmp_path)

    class Identifiers:
        MESSAGE = "message.db"
        CALL = "call.db"

    assert ios_crypt.is_e2e_backup(str(backup))
    ios_crypt.decrypt_e2e_backup(str(backup), KEY.hex(), Identifiers)
    assert (tmp_path / "message.db").read_bytes() == PLAINTEXT
    assert (tmp_path / "call.db").read_bytes() == b"calls"
