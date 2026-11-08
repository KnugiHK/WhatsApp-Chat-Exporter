#!/usr/bin/python3

import base64
import glob
import hashlib
import hmac
import logging
import os
import shutil
import string
import struct
from sys import exit
from typing import Iterator, List, Optional, Tuple
from Whatsapp_Chat_Exporter.android_crypt import DecryptionError, InvalidKeyError, InvalidFileFormatError

try:
    from Crypto.Cipher import AES
except ModuleNotFoundError:
    support_backup = False
else:
    support_backup = True

try:
    import lzfse
except ModuleNotFoundError:
    support_compression = False
else:
    support_compression = True


HEADER_LENGTH = 18
TAG_LENGTH = 32
FLAG_COMPRESSED = 0x80
KEY_TYPE_MASK = 0x7F
KEY_TYPE_E2E_SEPARATE_HMAC = 0x03
MESSAGE_FILE = "ChatStorage.sqlite.enc"
CALL_FILE = "CallHistory.sqlite.enc"
TAR_BLOCK_SIZE = 512
TAR_TYPE_ENCRYPTED = b"W"


def _hkdf(key: bytes, info: bytes, length: int = 32, salt: bytes = b"\x00" * 32) -> bytes:
    """HKDF-SHA256. WhatsApp starts the expand counter at 0, unlike RFC 5869."""
    prk = hmac.new(salt, key, hashlib.sha256).digest()
    output = b""
    block = b""
    counter = 0
    while len(output) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        output += block
        counter += 1
    return output[:length]


def _decompress(data: bytes) -> bytes:
    """Decompress Apple's pbze stream: a 12-byte header followed by LZFSE blocks."""
    if data[:4] != b"pbze":
        raise InvalidFileFormatError("The decrypted data is not a pbze stream.")
    position = 12
    output = bytearray()
    while position < len(data):
        if position + 16 > len(data):
            raise InvalidFileFormatError("The pbze stream is truncated.")
        raw_size, compressed_size = struct.unpack_from(">QQ", data, position)
        position += 16
        block = data[position:position + compressed_size]
        position += compressed_size
        if compressed_size != raw_size:
            block = lzfse.decompress(block)
        if len(block) != raw_size:
            raise InvalidFileFormatError("A pbze block has an unexpected size.")
        output += block
    return bytes(output)


def decrypt_file(data: bytes, key: bytes) -> bytes:
    """Decrypt the content of one .enc file from an iOS end-to-end encrypted backup.

    Args:
        data (bytes): The content of the .enc file.
        key (bytes): The 32-byte backup key.

    Returns:
        bytes: The decrypted content.

    Raises:
        InvalidFileFormatError: If the file is not a supported end-to-end encrypted file.
        InvalidKeyError: If the key does not match the file.
    """
    if len(data) < HEADER_LENGTH + TAG_LENGTH + AES.block_size:
        raise InvalidFileFormatError("The file is too short.")
    if data[0] & KEY_TYPE_MASK != KEY_TYPE_E2E_SEPARATE_HMAC:
        raise InvalidFileFormatError(
            f"Unsupported file type {data[0]:#x}. The backup may not be end-to-end encrypted."
        )
    body, tag = data[:-TAG_LENGTH], data[-TAG_LENGTH:]
    mac = hmac.new(_hkdf(key, b"file-verify"), body, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, tag):
        raise InvalidKeyError("The key is incorrect or the file is corrupted.")

    cipher = AES.new(_hkdf(key, b"file"), AES.MODE_CBC, data[2:HEADER_LENGTH])
    plaintext = cipher.decrypt(body[HEADER_LENGTH:])
    padding = plaintext[-1]
    if not 1 <= padding <= AES.block_size or plaintext[-padding:] != bytes([padding]) * padding:
        raise InvalidFileFormatError("The decrypted data has invalid padding.")
    plaintext = plaintext[:-padding]
    return _decompress(plaintext) if data[0] & FLAG_COMPRESSED else plaintext


def decrypt_tar_entry(name: bytes, data: bytes, tar_key: bytes) -> Tuple[str, bytes, bool]:
    """Decrypt one entry of a media tar file.

    Args:
        name (bytes): The entry name from the tar header.
        data (bytes): The entry content.
        tar_key (bytes): The key derived from the backup key for tar files.

    Returns:
        Tuple[str, bytes, bool]: The original file path, the file content or, for a link,
            the path of the linked file, and whether the entry is a link.

    Raises:
        InvalidFileFormatError: If the entry is malformed.
        InvalidKeyError: If the key does not match the entry.
    """
    if len(data) < TAG_LENGTH + AES.block_size or (len(data) - TAG_LENGTH) % AES.block_size:
        raise InvalidFileFormatError("The tar entry has an invalid size.")
    derived = _hkdf(tar_key, b"\x00", 80, base64.urlsafe_b64decode(name))
    encryption_key, mac_key, iv = derived[:32], derived[32:64], derived[64:]
    ciphertext, tag = data[:-TAG_LENGTH], data[-TAG_LENGTH:]
    if not hmac.compare_digest(hmac.new(mac_key, iv + ciphertext, hashlib.sha256).digest(), tag):
        raise InvalidKeyError("The key is incorrect or the tar entry is corrupted.")

    plaintext = AES.new(encryption_key, AES.MODE_CBC, iv).decrypt(ciphertext)
    padding = plaintext[-1]
    if not 1 <= padding <= AES.block_size or plaintext[-padding:] != bytes([padding]) * padding:
        raise InvalidFileFormatError("The decrypted tar entry has invalid padding.")
    plaintext = plaintext[:-padding]

    # [version][is link][u64 timestamp][u8 path length][path], followed by
    # [link target] for links or [u64 size][content] for files.
    if len(plaintext) < 11 or plaintext[0] != 1 or plaintext[1] > 1:
        raise InvalidFileFormatError("Unsupported tar entry header.")
    path_end = 11 + plaintext[10]
    path = plaintext[11:path_end].decode("utf-8")
    if plaintext[1] == 1:
        return path, plaintext[path_end:], True
    if len(plaintext) < path_end + 8:
        raise InvalidFileFormatError("The tar entry header is truncated.")
    size = struct.unpack_from(">Q", plaintext, path_end)[0]
    content = plaintext[path_end + 8:]
    if len(content) != size:
        raise InvalidFileFormatError("The tar entry content has an unexpected size.")
    return path, content, False


def _iter_tar_entries(path: str) -> Iterator[Tuple[bytes, bytes, bytes]]:
    """Yield (name, type flag, content) for each entry of a tar file."""
    with open(path, "rb") as f:
        while True:
            header = f.read(TAR_BLOCK_SIZE)
            if len(header) < TAR_BLOCK_SIZE:
                return
            if header == b"\x00" * TAR_BLOCK_SIZE:
                continue
            checksum = sum(header[:148]) + 8 * 32 + sum(header[156:])
            try:
                stored_checksum = int(header[148:156].split(b"\x00")[0].strip() or b"0", 8)
                size = int(header[124:136].split(b"\x00")[0].strip() or b"0", 8)
            except ValueError:
                raise InvalidFileFormatError(f"Invalid tar header in {path}.")
            if checksum != stored_checksum:
                raise InvalidFileFormatError(f"Invalid tar header in {path}.")
            content = f.read(size)
            f.seek((TAR_BLOCK_SIZE - size % TAR_BLOCK_SIZE) % TAR_BLOCK_SIZE, os.SEEK_CUR)
            yield header[:100].split(b"\x00")[0], header[156:157], content


def _safe_media_path(destination: str, relative_path: str) -> str:
    """Resolve a path inside the destination, refusing paths that escape it."""
    root = os.path.abspath(destination)
    target = os.path.abspath(os.path.join(root, relative_path.lstrip("/")))
    if not target.startswith(root + os.sep):
        raise InvalidFileFormatError(f"Refusing to use a path outside the media directory: {relative_path}")
    return target


def _write_media_file(destination: str, relative_path: str, content: bytes) -> None:
    """Write a media file to the destination."""
    target = _safe_media_path(destination, relative_path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as f:
        f.write(content)


def _create_media_links(destination: str, links: List[Tuple[str, str]]) -> None:
    """Copy linked files to their paths once every tar file has been extracted."""
    missing = 0
    for relative_path, link_target in links:
        source = _safe_media_path(destination, link_target)
        target = _safe_media_path(destination, relative_path)
        if not os.path.isfile(source):
            missing += 1
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(source, target)
    if missing:
        logging.warning(f"{missing} linked media files were not found in the backup.")


def extract_e2e_media(base_dir: str, backup_key: bytes, media_dir: str) -> None:
    """Decrypt the media tar files of an end-to-end encrypted backup to the media directory."""
    tar_key = _hkdf(backup_key, b"tar")
    destination = os.path.join(media_dir, "Message")
    links = []
    for path in sorted(glob.glob(os.path.join(base_dir, "*.tar"))):
        extracted = skipped = 0
        for name, entry_type, content in _iter_tar_entries(path):
            if entry_type != TAR_TYPE_ENCRYPTED:
                skipped += 1
                continue
            relative_path, data, is_link = decrypt_tar_entry(name, content, tar_key)
            if is_link:
                links.append((relative_path, data.decode("utf-8")))
            else:
                _write_media_file(destination, relative_path, data)
            extracted += 1
        logging.info(f"Decrypted {extracted} files from {os.path.basename(path)}")
        if skipped:
            logging.warning(
                f"Skipped {skipped} unencrypted entries in {os.path.basename(path)}. "
                "It may be from an earlier backup that has not finished updating."
            )
    _create_media_links(destination, links)


def is_e2e_backup(base_dir: str) -> bool:
    """Check whether a directory is an iOS end-to-end encrypted backup."""
    return os.path.isfile(os.path.join(base_dir, MESSAGE_FILE))


def parse_key(key: str) -> bytes:
    """Read the 64-digit key from a hex string or from a file containing one."""
    if os.path.isfile(key):
        with open(key, "r") as f:
            key = f.read()
    key = "".join(key.split())
    if len(key) != 64 or not all(char in string.hexdigits for char in key):
        raise InvalidKeyError("The key must be 64 hexadecimal digits.")
    return bytes.fromhex(key)


def decrypt_e2e_backup(base_dir: str, key: str, identifiers, media_dir: Optional[str] = None) -> None:
    """Decrypt an iOS end-to-end encrypted backup.

    Databases are written to the working directory and media to media_dir.

    Args:
        base_dir (str): The directory containing the .enc and .tar files.
        key (str): The 64-digit key, or the path to a file containing it.
        identifiers: An object containing WhatsApp file identifiers.
        media_dir (Optional[str]): The media directory, or None to skip media extraction.
    """
    if not support_backup or not support_compression:
        logging.error(
            "Dependencies for iOS end-to-end encrypted backups are not available. "
            "Install them with: pip install whatsapp-chat-exporter[ios_e2e]"
        )
        exit(1)
    try:
        backup_key = parse_key(key)
        for name, target in ((MESSAGE_FILE, identifiers.MESSAGE), (CALL_FILE, identifiers.CALL)):
            path = os.path.join(base_dir, name)
            if not os.path.isfile(path):
                logging.warning(f"{name} not found. Skipping...")
                continue
            with open(path, "rb") as f:
                decrypted = decrypt_file(f.read(), backup_key)
            with open(target, "wb") as f:
                f.write(decrypted)
            logging.info(f"Decrypted {name}")
        if media_dir is not None:
            extract_e2e_media(base_dir, backup_key, media_dir)
    except DecryptionError as e:
        logging.error(f"Failed to decrypt the backup: {e}")
        exit(1)
