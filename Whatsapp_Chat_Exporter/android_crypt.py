import hmac
import io
import logging
import zlib
import concurrent.futures
from tqdm import tqdm
from typing import Tuple, Union
from hashlib import sha256
from functools import partial
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




class DecryptionError(Exception):
    """Base class for decryption-related exceptions."""
    pass


class InvalidKeyError(DecryptionError):
    """Raised when the provided key is invalid."""
    pass


class InvalidFileFormatError(DecryptionError):
    """Raised when the input file format is invalid."""
    pass


class OffsetNotFoundError(DecryptionError):
    """Raised when the correct offsets for decryption cannot be found."""
    pass


def _derive_main_enc_key(key_stream: bytes) -> Tuple[bytes, bytes]:
    """
    Derive the main encryption key for the given key stream.

    Args:
        key_stream (bytes): The key stream to generate HMAC of HMAC.

    Returns:
        Tuple[bytes, bytes]: A tuple containing the main encryption key and the original key stream.
    """
    intermediate_hmac = hmac.new(b'\x00' * 32, key_stream, sha256).digest()
    key = hmac.new(intermediate_hmac, b"backup encryption\x01", sha256).digest()
    return key, key_stream


def _extract_enc_key(keyfile: bytes) -> Tuple[bytes, bytes]:
    """
    Extract the encryption key from the keyfile.

    Args:
        keyfile (bytes): The keyfile containing the encrypted key.

    Returns:
        Tuple[bytes, bytes]: values from _derive_main_enc_key()
    """
    key_stream = b''.join([byte.to_bytes(1, "big", signed=True) for byte in javaobj.loads(keyfile)])
    return _derive_main_enc_key(key_stream)


def brute_force_offset(max_iv: int = 200, max_db: int = 200):
    """
    Brute force the offsets for IV and database start position in WhatsApp backup files.

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


def _decrypt_database(db_ciphertext: bytes, main_key: bytes, iv: bytes) -> bytes:
    """Decrypt and decompress a database chunk.

        Args:
            db_ciphertext (bytes): The encrypted chunk of the database.
            main_key (bytes): The main decryption key.
            iv (bytes): The initialization vector.

        Returns:
            bytes: The decrypted and decompressed database.

        Raises:
            zlib.error: If decompression fails.
            ValueError: if the plaintext is not a SQLite database.
    """
    FOOTER_SIZE = 32
    if len(db_ciphertext) <= FOOTER_SIZE:
        raise ValueError("Input data too short to contain a valid GCM tag.")
    
    actual_ciphertext = db_ciphertext[:-FOOTER_SIZE]
    tag = db_ciphertext[-FOOTER_SIZE: -FOOTER_SIZE + 16]

    cipher = AES.new(main_key, AES.MODE_GCM, iv)
    try:
        db_compressed = cipher.decrypt_and_verify(actual_ciphertext, tag)
    except ValueError:
        # This could be key, IV, or tag is wrong, but likely the key is wrong.
        raise ValueError("Decryption/Authentication failed. Ensure you are using the correct key.")

    if len(db_compressed) < 2 or db_compressed[0] != 0x78:
        logging.debug(f"Data passes GCM but is not Zlib. Header: {db_compressed[:2].hex()}")
        raise ValueError(
            "Key is correct, but decrypted data is not a valid compressed stream. "
            "Is this even a valid WhatsApp database backup?"
        )

    try:
        db = zlib.decompress(db_compressed)
    except zlib.error as e:
        raise zlib.error(f"Decompression failed (The backup file likely corrupted at source): {e}")

    if not db.startswith(b"SQLite"):
        raise ValueError(
            "Data is valid and decompressed, but it is not a SQLite database. "
            "Is this even a valid WhatsApp database backup?")
    return db


def _decrypt_crypt14(database: bytes, main_key: bytes, max_worker: int = 10) -> bytes:
    """Decrypt a crypt14 database using multithreading for brute-force offset detection.

    Args:
        database (bytes): The encrypted database.
        main_key (bytes): The decryption key.
        max_worker (int, optional): The maximum number of threads to use for brute force. Defaults to 10.

    Returns:
        bytes: The decrypted database.

    Raises:
        InvalidFileFormatError: If the file is too small.
        OffsetNotFoundError: If no valid offsets are found.
    """
    if len(database) < 191:
        raise InvalidFileFormatError("The crypt14 file must be at least 191 bytes")

    # Attempt known offsets first
    for offsets in CRYPT14_OFFSETS:
        iv = offsets["iv"]
        db = offsets["db"]
        try:
            decrypted_db = _attempt_decrypt_task((iv, iv + 16, db), database, main_key)
        except (zlib.error, ValueError):
            continue
        else:
            logging.debug(
                f"Decryption successful with known offsets: IV {iv}, DB {db}"
            )
            return decrypted_db  # Successful decryption

    logging.info(f"Common offsets failed. Will attempt to brute-force")
    offset_max = 200
    workers = max_worker
    check_offset = partial(_attempt_decrypt_task, database=database, main_key=main_key)
    all_offsets = list(brute_force_offset(offset_max, offset_max))
    executor = concurrent.futures.ProcessPoolExecutor(max_workers=workers)
    try:
        with tqdm(total=len(all_offsets), desc="Brute-forcing offsets", unit="trial", leave=False) as pbar:
            results = executor.map(check_offset, all_offsets, chunksize=8)
            found = False
            for offset_info, result in zip(all_offsets, results):
                pbar.update(1)
                if result:
                    start_iv, _, start_db = offset_info
                    # Clean shutdown on success
                    executor.shutdown(wait=False, cancel_futures=True)
                    found = True
                    break
        if found:
            logging.info(
                f"The offsets of your IV and database are {start_iv} and {start_db}, respectively."
            )
            logging.info(
                f"To include your offsets in the expoter, please report it in the discussion thread on GitHub:"
            )
            logging.info(f"https://github.com/KnugiHK/Whatsapp-Chat-Exporter/discussions/47")
            return result

    except KeyboardInterrupt:
        executor.shutdown(wait=False, cancel_futures=True)
        logging.info("")
        raise KeyboardInterrupt(
            f"Brute force interrupted by user (Ctrl+C). Shutting down gracefully..."
        )
    
    finally:
        executor.shutdown(wait=False)

    raise OffsetNotFoundError("Could not find the correct offsets for decryption.")

def _attempt_decrypt_task(offset_tuple, database, main_key):
    """Attempt decryption with the given offsets."""
    start_iv, end_iv, start_db = offset_tuple
    iv = database[start_iv:end_iv]
    db_ciphertext = database[start_db:]
    
    try:
        return _decrypt_database(db_ciphertext, main_key, iv)
    except (zlib.error, ValueError):
        return None


def _decrypt_crypt12(database: bytes, main_key: bytes) -> bytes:
    """Decrypt a crypt12 database.

        Args:
            database (bytes): The encrypted database.
            main_key (bytes): The decryption key.

        Returns:
            bytes: The decrypted database.

        Raises:
            ValueError: If the file format is invalid or the signature mismatches.
    """
    if len(database) < 67:
        raise InvalidFileFormatError("The crypt12 file must be at least 67 bytes")

    t2 = database[3:35]
    iv = database[51:67]
    db_ciphertext = database[67:-20]
    return _decrypt_database(db_ciphertext, main_key, iv)


def _decrypt_crypt15(database: bytes, main_key: bytes, db_type: DbType) -> bytes:
    """Decrypt a crypt15 database.

        Args:
            database (bytes): The encrypted database.
            main_key (bytes): The decryption key.
            db_type (DbType): The type of database.

        Returns:
            bytes: The decrypted database.

        Raises:
            ValueError: If the file format is invalid or the signature mismatches.
    """
    if not support_crypt15:
        raise RuntimeError("Crypt15 is not supported")
    if len(database) < 131:
        raise InvalidFileFormatError("The crypt15 file must be at least 131 bytes")

    if db_type == DbType.MESSAGE:
        iv = database[8:24]
        db_offset = database[0] + 2
    elif db_type == DbType.CONTACT:
        iv = database[7:23]
        db_offset = database[0] + 1
    else:
        raise ValueError(f"Invalid db_type: {db_type}")

    db_ciphertext = database[db_offset:]
    return _decrypt_database(db_ciphertext, main_key, iv)


def decrypt_backup(
    database: bytes,
    key: Union[str, io.IOBase],
    output: str = None,
    crypt: Crypt = Crypt.CRYPT14,
    show_crypt15: bool = False,
    db_type: DbType = DbType.MESSAGE,
    *,
    dry_run: bool = False,
    keyfile_stream: bool = False,
    max_worker: int = 10
) -> int:
    """
    Decrypt the WhatsApp backup database.

    Args:
        database (bytes): The encrypted database file.
        key (str or io.IOBase): The key to decrypt the database.
        output (str, optional): The path to save the decrypted database. Defaults to None.
        crypt (Crypt, optional): The encryption version of the database. Defaults to Crypt.CRYPT14.
        show_crypt15 (bool, optional): Whether to show the HEX key of the crypt15 backup. Defaults to False.
        db_type (DbType, optional): The type of database (MESSAGE or CONTACT). Defaults to DbType.MESSAGE.
        dry_run (bool, optional): Whether to perform a dry run. Defaults to False.
        keyfile_stream (bool, optional): Whether the key is a key stream. Defaults to False.

    Returns:
        int: The status code of the decryption process (0 for success).

    Raises:
        ValueError: If the key is invalid or output file not provided when dry_run is False.
        DecryptionError: for errors during decryption
        RuntimeError: for dependency errors
    """
    if not support_backup:
        raise RuntimeError("Dependencies for backup decryption are not available.")

    if not dry_run and output is None:
        raise ValueError(
            "The path to the decrypted database must be specified unless dry_run is true."
        )

    if isinstance(key, io.IOBase):
        key = key.read()

    if crypt is not Crypt.CRYPT15 and len(key) != 158:
        raise InvalidKeyError("The key file must be 158 bytes")

    # signature check, this is check is used in crypt 12 and 14
    if crypt != Crypt.CRYPT15:
        t1 = key[30:62]

        if t1 != database[15:47] and crypt == Crypt.CRYPT14:
            raise ValueError("The signature of key file and backup file mismatch")

        if t1 != database[3:35] and crypt == Crypt.CRYPT12:
            raise ValueError("The signature of key file and backup file mismatch")

    if crypt == Crypt.CRYPT15:
        if keyfile_stream:
            main_key, hex_key = _extract_enc_key(key)
        else:
            main_key, hex_key = _derive_main_enc_key(key)
        if show_crypt15:
            hex_key_str = ' '.join([hex_key.hex()[c:c+4] for c in range(0, len(hex_key.hex()), 4)])
            logging.info(f"The HEX key of the crypt15 backup is: {hex_key_str}")
    else:
        main_key = key[126:]

    try:
        if crypt == Crypt.CRYPT14:
            db = _decrypt_crypt14(database, main_key, max_worker)
        elif crypt == Crypt.CRYPT12:
            db = _decrypt_crypt12(database, main_key)
        elif crypt == Crypt.CRYPT15:
            db = _decrypt_crypt15(database, main_key, db_type)
        else:
            raise ValueError(f"Unsupported crypt type: {crypt}")
    except (InvalidFileFormatError, OffsetNotFoundError, ValueError) as e:
        raise DecryptionError(f"Decryption failed: {e}") from e

    if not dry_run:
        with open(output, "wb") as f:
            f.write(db)
    return 0
