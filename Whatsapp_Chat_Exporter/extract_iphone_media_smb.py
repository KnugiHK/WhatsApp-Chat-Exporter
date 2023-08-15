#!/usr/bin/python3

import shutil
import sqlite3
import os
import time
import getpass
import threading
try:
    from iphone_backup_decrypt import EncryptedBackup, RelativePath
    from iphone_backup_decrypt import FailedToDecryptError, Domain
except ModuleNotFoundError:
    support_encrypted = False
else:
    support_encrypted = True


def extract_encrypted(base_dir, password):
    backup = EncryptedBackup(backup_directory=base_dir, passphrase=password, cleanup=False, check_same_thread=False)
    print("Decrypting WhatsApp database...")
    try:
        backup.extract_file(relative_path=RelativePath.WHATSAPP_MESSAGES,
                        output_filename="724bd3b98b18518b455a87c1f3ac3a0d189c4466")
        backup.extract_file(relative_path=RelativePath.WHATSAPP_CONTACTS,
                            output_filename="d7246a707f51ddf8b17ee2dddabd9e0a4da5c552")
    except FailedToDecryptError:
        print("Failed to decrypt backup: incorrect password?")
        exit()
    extract_thread = threading.Thread(
        target=backup.extract_files_by_domain,
        args=(Domain.WHATSAPP, Domain.WHATSAPP)
    )
    extract_thread.daemon = True
    extract_thread.start()
    dot = 0
    while extract_thread.is_alive():
        print(f"Decrypting and extracting files{'.' * dot}{' ' * (3 - dot)}", end="\r")
        if dot < 3:
            dot += 1
            time.sleep(0.5)
        else:
            dot = 0
            time.sleep(0.4)
    print(f"All required files decrypted and extracted.", end="\n")
    extract_thread.handled = True
    return backup


def is_encrypted(base_dir):
    with sqlite3.connect(os.path.join(base_dir, "Manifest.db")) as f:
        c = f.cursor()
        try:
            c.execute("""SELECT count()
                    FROM Files
                    """)
        except sqlite3.OperationalError as e:
            raise e  # These error cannot be used to determine if the backup is encrypted
        except sqlite3.DatabaseError:
            return True
        else:
            return False


def extract_media(base_dir):
    if is_encrypted(base_dir):
        if not support_encrypted:
            print("You don't have the dependencies to handle encrypted backup.")
            print("Read more on how to deal with encrypted backup:")
            print("https://github.com/KnugiHK/Whatsapp-Chat-Exporter/blob/main/README.md#usage")
            return False
        print("Encryption detected on the backup!")
        password = getpass.getpass("Enter the password for the backup:")
        extract_encrypted(base_dir, password)
    else:
        wts_db = os.path.join(base_dir, "72/724bd3b98b18518b455a87c1f3ac3a0d189c4466")
        contact_db = os.path.join(base_dir, "d7/d7246a707f51ddf8b17ee2dddabd9e0a4da5c552")
        if not os.path.isfile(wts_db):
            print("WhatsApp database not found.")
            exit()
        else:
            shutil.copyfile(wts_db, "724bd3b98b18518b455a87c1f3ac3a0d189c4466")
        if not os.path.isfile(contact_db):
            print("Contact database not found.")
            exit()
        else:
            shutil.copyfile(contact_db, "d7246a707f51ddf8b17ee2dddabd9e0a4da5c552")
        _wts_id = "AppDomainGroup-group.net.whatsapp.WhatsAppSMB.shared"
        with sqlite3.connect(os.path.join(base_dir, "Manifest.db")) as manifest:
            manifest.row_factory = sqlite3.Row
            c = manifest.cursor()
            c.execute(
                f"""SELECT count()
                    FROM Files
                    WHERE domain = '{_wts_id}'"""
            )
            total_row_number = c.fetchone()[0]
            print(f"Extracting WhatsApp files...(0/{total_row_number})", end="\r")
            c.execute(f"""SELECT fileID,
                                relativePath,
                                flags,
                                ROW_NUMBER() OVER(ORDER BY relativePath) AS _index
                        FROM Files
                        WHERE domain = '{_wts_id}'
                        ORDER BY relativePath""")
            if not os.path.isdir(_wts_id):
                os.mkdir(_wts_id)
            row = c.fetchone()
            while row is not None:
                if row["relativePath"] == "":
                    row = c.fetchone()
                    continue
                destination = os.path.join(_wts_id, row["relativePath"])
                hashes = row["fileID"]
                folder = hashes[:2]
                flags = row["flags"]
                if flags == 2:
                    try:
                        os.mkdir(destination)
                    except FileExistsError:
                        pass
                elif flags == 1:
                    shutil.copyfile(os.path.join(base_dir, folder, hashes), destination)
                if row["_index"] % 100 == 0:
                    print(f"Extracting WhatsApp files...({row['_index']}/{total_row_number})", end="\r")
                row = c.fetchone()
            print(f"Extracting WhatsApp files...({total_row_number}/{total_row_number})", end="\n")
