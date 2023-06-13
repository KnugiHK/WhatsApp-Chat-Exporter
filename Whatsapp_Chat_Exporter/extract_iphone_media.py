#!/usr/bin/python3

import shutil
import sqlite3
import os
import getpass
try:
    from iphone_backup_decrypt import EncryptedBackup, RelativePath
except ModuleNotFoundError:
    support_encrypted = False
else:
    support_encrypted = True


def extract_encrypted(base_dir, password):
    backup = EncryptedBackup(backup_directory=base_dir, passphrase=password)
    print("Decrypting WhatsApp database...")
    backup.extract_file(relative_path=RelativePath.WHATSAPP_MESSAGES,
                        output_filename="7c7fba66680ef796b916b067077cc246adacf01d")
    backup.extract_file(relative_path=RelativePath.WHATSAPP_CONTACTS,
                        output_filename="ContactsV2.sqlite")
    data = backup.execute_sql("""SELECT count()
                                FROM Files
                                WHERE relativePath
                                    LIKE 'Message/Media/%'"""
                              )
    total_row_number = data[0][0]
    print(f"Extracting media...(0/{total_row_number})", end="\r")
    data = backup.execute_sql("""SELECT fileID,
                                        relativePath,
                                        flags,
                                        file
                                FROM Files
                                WHERE relativePath
                                    LIKE 'Message/Media/%'"""
                              )
    if not os.path.isdir("Message"):
        os.mkdir("Message")
    if not os.path.isdir("Message/Media"):
        os.mkdir("Message/Media")
    i = 0
    for row in data:
        destination = row[1]
        hashes = row[0]
        folder = hashes[:2]
        flags = row[2]
        file = row[3]
        if flags == 2:
            try:
                os.mkdir(destination)
            except FileExistsError:
                pass
        elif flags == 1:
            decrypted = backup.decrypt_inner_file(file_id=hashes, file_bplist=file)
            with open(destination, "wb") as f:
                f.write(decrypted)
        i += 1
        if i % 100 == 0:
            print(f"Extracting media...({i}/{total_row_number})", end="\r")
    print(f"Extracting media...({total_row_number}/{total_row_number})", end="\n")


def is_encrypted(base_dir):
    with sqlite3.connect(f"{base_dir}/Manifest.db") as f:
        c = f.cursor()
        try:
            c.execute("""SELECT count()
                    FROM Files
                    """)
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
        password = getpass.getpass("Enter the password:")
        extract_encrypted(base_dir, password)
    else:
        wts_db = os.path.join(base_dir, "7c/7c7fba66680ef796b916b067077cc246adacf01d")
        contact_db = os.path.join(base_dir, "b8/b8548dc30aa1030df0ce18ef08b882cf7ab5212f")
        if not os.path.isfile(wts_db):
            print("WhatsApp database not found.")
            exit()
        else:
            shutil.copyfile(wts_db, "7c7fba66680ef796b916b067077cc246adacf01d")
        if not os.path.isfile(contact_db):
            print("Contact database not found.")
            exit()
        else:
            shutil.copyfile(contact_db, "b8548dc30aa1030df0ce18ef08b882cf7ab5212f")    
        _wts_id = "AppDomainGroup-group.net.whatsapp.WhatsApp.shared"
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
            if not os.path.isdir("WhatsApp"):
                os.mkdir("WhatsApp")
            row = c.fetchone()
            while row is not None:
                if row["relativePath"] == "":
                    row = c.fetchone()
                    continue
                destination = os.path.join("WhatsApp/", row["relativePath"])
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


if __name__ == "__main__":
    from optparse import OptionParser
    parser = OptionParser()
    (_, args) = parser.parse_args()
    base_dir = args[0]
    extract_media(base_dir)
