import hmac
import io
import zlib
import javaobj
from typing import Tuple, Union
from hashlib import sha256
from Whatsapp_Chat_Exporter.utility import CRYPT14_OFFSETS, Crypt, DbType
try:
    import zlib
    from Crypto.Cipher import AES
except ModuleNotFoundError:
    support_backup = False
else:
    support_backup = True
try:
    import javaobj
except ModuleNotFoundError:
    support_crypt15 = False
else:
    support_crypt15 = True


def _derive_main_enc_key(key_stream: bytes) -> Tuple[bytes, bytes]:
    """
    Derive the main encryption key for the given key stream. The key is derived using HMAC of HMAC of the provided key stream.

    Args:
        key_stream (bytes): The key stream to generate HMAC of HMAC.

    Returns:
        Tuple[bytes, bytes]: A tuple containing the main encryption key and the original key stream.
    """
    key = hmac.new(
        hmac.new(
            b'\x00' * 32,
            key_stream,
            sha256
        ).digest(),
        b"backup encryption\x01",
        sha256
    )
    return key.digest(), key_stream


def _extract_enc_key(keyfile: bytes) -> Tuple[bytes, bytes]:
    """
    Extract the encryption key from the keyfile.

    Args:
        keyfile (bytes): The keyfile containing the encrypted key.

    Returns:
        Tuple[bytes, bytes]: values from _derive_main_enc_key()
    """
    key_stream = b""
    for byte in javaobj.loads(keyfile):
        key_stream += byte.to_bytes(1, "big", signed=True)

    return _derive_main_enc_key(key_stream)


def brute_force_offset(max_iv: int = 200, max_db: int = 200):
    """
    Brute force the offsets for IV and database start position in WhatsApp backup files.
    Used when common offsets are not applicable to a backup file.

    Args:
        max_iv (int, optional): Maximum value to try for IV offset. Defaults to 200.
        max_db (int, optional): Maximum value to try for database start offset. Defaults to 200.

    Yields:
        tuple: A tuple containing:
            - int: Start position of IV
            - int: End position of IV (start + 16)
            - int: Start position of database
    """
    for iv in range(0, max_iv):
        for db in range(0, max_db):
            yield iv, iv + 16, db


def decrypt_backup(
    database: bytes,
    key: Union[str, io.IOBase],
    output: str = None,
    crypt: Crypt = Crypt.CRYPT14,
    show_crypt15: bool = False,
    db_type: DbType = DbType.MESSAGE,
    dry_run: bool = False,
    key_stream: bool = False
) -> int:
    """
    Decrypt the WhatsApp backup database.

    Args:
        database (bytes): The encrypted database file.
        key (str or io.IOBase): The key to decrypt the database. The key should either be a string (32 bytes hex key) or a file object (encryption key file).
        key_stream (bool, optional): Whether the key is a key stream. False for hex key. True for key stream.
        output (str, optional): The path to save the decrypted database. Defaults to None. When dry_run is True, this parameter is ignored.
        crypt (Crypt, optional): The encryption version of the database. Defaults to Crypt.CRYPT14.
        show_crypt15 (bool, optional): Whether to show the HEX key of the crypt15 backup. Defaults to False.
        db_type (DbType, optional): The type of database (MESSAGE or CONTACT). Defaults to DbType.MESSAGE.
        dry_run (bool, optional): Whether to perform a dry run without saving the decrypted database. Defaults to False.

    Returns:
        int: The status code of the decryption process.
            - 0: The decryption process was successful.
            - 1: The decryption process failed because the necessary dependencies for backup decryption are not available.
            - 2: The decryption process failed because the common offsets for the IV and database are not applicable, and the brute force attempt to find the correct offsets also failed.
            - 3: The decryption process failed due to unknown error
    """
    if not support_backup:
        return 1
    if not dry_run and output is None:
        ValueError("The path to the decrypted database must be specified unless dry_run is true.")
    if isinstance(key, io.IOBase):
        key = key.read()
        if crypt is not Crypt.CRYPT15:
            t1 = key[30:62]
    if crypt is not Crypt.CRYPT15 and len(key) != 158:
        raise ValueError("The key file must be 158 bytes")
    # Determine the IV and database offsets
    if crypt == Crypt.CRYPT14:
        if len(database) < 191:
            raise ValueError("The crypt14 file must be at least 191 bytes")
        current_try = 0
        offsets = CRYPT14_OFFSETS[current_try]
        t2 = database[15:47]
        iv = database[offsets["iv"]:offsets["iv"] + 16]
        db_ciphertext = database[offsets["db"]:]
    elif crypt == Crypt.CRYPT12:
        if len(database) < 67:
            raise ValueError("The crypt12 file must be at least 67 bytes")
        t2 = database[3:35]
        iv = database[51:67]
        db_ciphertext = database[67:-20]
    elif crypt == Crypt.CRYPT15:
        if not support_crypt15:
            return 1
        if len(database) < 131:
            raise ValueError("The crypt15 file must be at least 131 bytes")
        t1 = t2 = None
        if db_type == DbType.MESSAGE:
            iv = database[8:24]
            db_offset = database[0] + 2  # Skip protobuf + protobuf size and backup type
        elif db_type == DbType.CONTACT:
            iv = database[7:23]
            db_offset = database[0] + 1  # Skip protobuf + protobuf size
        db_ciphertext = database[db_offset:]

    if t1 != t2:
        raise ValueError("The signature of key file and backup file mismatch")

    if crypt == Crypt.CRYPT15:
        if key_stream:
            main_key, hex_key = _extract_enc_key(key)
        else:
            main_key, hex_key = _derive_main_enc_key(key)
        if show_crypt15:
            hex_key = [hex_key.hex()[c:c+4] for c in range(0, len(hex_key.hex()), 4)]
            print("The HEX key of the crypt15 backup is: " + ' '.join(hex_key))
    else:
        main_key = key[126:]
    decompressed = False
    while not decompressed:
        cipher = AES.new(main_key, AES.MODE_GCM, iv)
        db_compressed = cipher.decrypt(db_ciphertext)
        try:
            db = zlib.decompress(db_compressed)
        except zlib.error:
            if crypt == Crypt.CRYPT14:
                current_try += 1
                if current_try < len(CRYPT14_OFFSETS):
                    offsets = CRYPT14_OFFSETS[current_try]
                    iv = database[offsets["iv"]:offsets["iv"] + 16]
                    db_ciphertext = database[offsets["db"]:]
                    continue
                else:
                    print("Common offsets are not applicable to "
                          "your backup. Trying to brute force it...")
                    for start_iv, end_iv, start_db in brute_force_offset():
                        iv = database[start_iv:end_iv]
                        db_ciphertext = database[start_db:]
                        cipher = AES.new(main_key, AES.MODE_GCM, iv)
                        db_compressed = cipher.decrypt(db_ciphertext)
                        try:
                            db = zlib.decompress(db_compressed)
                        except zlib.error:
                            continue
                        else:
                            decompressed = True
                            print(
                                f"The offsets of your IV and database are {start_iv} and "
                                f"{start_db}, respectively. To include your offsets in the "
                                "program, please report it by creating an issue on GitHub: "
                                "https://github.com/KnugiHK/Whatsapp-Chat-Exporter/discussions/47"
                            )
                            break
                    if not decompressed:
                        return 2
            else:
                return 3
        else:
            decompressed = True
        if db[0:6].upper() == b"SQLITE":
            if not dry_run:
                with open(output, "wb") as f:
                    f.write(db)
            return 0
        else:
            raise ValueError("The plaintext is not a SQLite database. Did you use the key to encrypt something...")
