import hmac
import javaobj
import zlib
from Crypto.Cipher import AES
from hashlib import sha256
from sys import exit


def _generate_hmac_of_hmac(key_stream):
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


def _extract_encrypted_key(keyfile):
    key_stream = b""
    for byte in javaobj.loads(keyfile):
        key_stream += byte.to_bytes(1, "big", signed=True)

    return _generate_hmac_of_hmac(key_stream)


key = open("encrypted_backup.key", "rb").read()
database = open("wa.db.crypt15", "rb").read()
main_key, hex_key = _extract_encrypted_key(key)
for i in range(100):
    iv = database[i:i+16]
    for j in range(100):
        cipher = AES.new(main_key, AES.MODE_GCM, iv)
        db_ciphertext = database[j:]
        db_compressed = cipher.decrypt(db_ciphertext)
        try:
            db = zlib.decompress(db_compressed)
        except zlib.error:
            ...
        else:
            if db[0:6] == b"SQLite":
                print(f"Found!\nIV: {i}\nOffset: {j}")
                print(db_compressed[:10])
                exit()

print("Not found! Try to increase maximum search.")
