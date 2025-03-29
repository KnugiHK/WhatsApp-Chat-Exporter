#!/usr/bin/python3

import shutil
import sqlite3
import os
import getpass
from Whatsapp_Chat_Exporter.utility import WhatsAppIdentifier
from Whatsapp_Chat_Exporter.bplist import BPListReader
try:
    from iphone_backup_decrypt import EncryptedBackup, RelativePath
except ModuleNotFoundError:
    support_encrypted = False
else:
    support_encrypted = True


class BackupExtractor:
    """
    A class to handle the extraction of WhatsApp data from iOS backups,
    including encrypted and unencrypted backups.
    """

    def __init__(self, base_dir, identifiers, decrypt_chunk_size):
        self.base_dir = base_dir
        self.identifiers = identifiers
        self.decrypt_chunk_size = decrypt_chunk_size

    def extract(self):
        """
        Extracts WhatsApp data from the backup based on whether it's encrypted or not.
        """
        if self._is_encrypted():
            self._extract_encrypted_backup()
        else:
            self._extract_unencrypted_backup()

    def _is_encrypted(self):
        """
        Checks if the iOS backup is encrypted.

        Returns:
            bool: True if encrypted, False otherwise.
        """
        with sqlite3.connect(os.path.join(self.base_dir, "Manifest.db")) as db:
            c = db.cursor()
            try:
                c.execute("SELECT count() FROM Files")
                c.fetchone()  # Execute and fetch to trigger potential errors
            except (sqlite3.OperationalError, sqlite3.DatabaseError):
                return True
            else:
                return False

    def _extract_encrypted_backup(self):
        """
        Handles the extraction of data from an encrypted iOS backup.
        """
        if not support_encrypted:
            print("You don't have the dependencies to handle encrypted backup.")
            print("Read more on how to deal with encrypted backup:")
            print("https://github.com/KnugiHK/Whatsapp-Chat-Exporter/blob/main/README.md#usage")
            return

        print("Encryption detected on the backup!")
        password = getpass.getpass("Enter the password for the backup:")
        self._decrypt_backup(password)
        self._extract_decrypted_files()

    def _decrypt_backup(self, password):
        """
        Decrypts the iOS backup using the provided password.

        Args:
            password (str): The password for the encrypted backup.
        """
        print("Trying to decrypt the iOS backup...", end="")
        self.backup = EncryptedBackup(
            backup_directory=self.base_dir,
            passphrase=password,
            cleanup=False,
            check_same_thread=False,
            decrypt_chunk_size=self.decrypt_chunk_size,
        )
        print("Done\nDecrypting WhatsApp database...", end="")
        try:
            self.backup.extract_file(
                relative_path=RelativePath.WHATSAPP_MESSAGES,
                domain_like=self.identifiers.DOMAIN,
                output_filename=self.identifiers.MESSAGE,
            )
            self.backup.extract_file(
                relative_path=RelativePath.WHATSAPP_CONTACTS,
                domain_like=self.identifiers.DOMAIN,
                output_filename=self.identifiers.CONTACT,
            )
            self.backup.extract_file(
                relative_path=RelativePath.WHATSAPP_CALLS,
                domain_like=self.identifiers.DOMAIN,
                output_filename=self.identifiers.CALL,
            )
        except ValueError:
            print("Failed to decrypt backup: incorrect password?")
            exit(7)
        except FileNotFoundError:
            print(
                "Essential WhatsApp files are missing from the iOS backup. "
                "Perhapse you enabled end-to-end encryption for the backup? "
                "See https://wts.knugi.dev/docs.html?dest=iose2e"
            )
            exit(6)
        else:
            print("Done")
    
    def _extract_decrypted_files(self):
        """Extract all WhatsApp files after decryption"""
        def extract_progress_handler(file_id, domain, relative_path, n, total_files):
            if n % 100 == 0:
                print(f"Decrypting and extracting files...({n}/{total_files})", end="\r")   
            return True

        self.backup.extract_files(
            domain_like=self.identifiers.DOMAIN,
            output_folder=self.identifiers.DOMAIN,
            preserve_folders=True,
            filter_callback=extract_progress_handler
        )
        print(f"All required files are decrypted and extracted.          ", end="\n")

    def _extract_unencrypted_backup(self):
        """
        Handles the extraction of data from an unencrypted iOS backup.
        """
        self._copy_whatsapp_databases()
        self._extract_media_files()

    def _copy_whatsapp_databases(self):
        """
        Copies the WhatsApp message, contact, and call databases to the working directory.
        """
        wts_db_path = os.path.join(self.base_dir, self.identifiers.MESSAGE[:2], self.identifiers.MESSAGE)
        contact_db_path = os.path.join(self.base_dir, self.identifiers.CONTACT[:2], self.identifiers.CONTACT)
        call_db_path = os.path.join(self.base_dir, self.identifiers.CALL[:2], self.identifiers.CALL)

        if not os.path.isfile(wts_db_path):
            if self.identifiers is WhatsAppIdentifier:
                print("WhatsApp database not found.")
            else:
                print("WhatsApp Business database not found.")
            print(
                "Essential WhatsApp files are missing from the iOS backup. "
                "Perhapse you enabled end-to-end encryption for the backup? "
                "See https://wts.knugi.dev/docs.html?dest=iose2e"
            )
            exit()
        else:
            shutil.copyfile(wts_db_path, self.identifiers.MESSAGE)

        if not os.path.isfile(contact_db_path):
            print("Contact database not found. Skipping...")
        else:
            shutil.copyfile(contact_db_path, self.identifiers.CONTACT)

        if not os.path.isfile(call_db_path):
            print("Call database not found. Skipping...")
        else:
            shutil.copyfile(call_db_path, self.identifiers.CALL)

    def _extract_media_files(self):
        """
        Extracts media files from the unencrypted backup.
        """
        _wts_id = self.identifiers.DOMAIN
        with sqlite3.connect(os.path.join(self.base_dir, "Manifest.db")) as manifest:
            manifest.row_factory = sqlite3.Row
            c = manifest.cursor()
            c.execute(f"SELECT count() FROM Files WHERE domain = '{_wts_id}'")
            total_row_number = c.fetchone()[0]
            print(f"Extracting WhatsApp files...(0/{total_row_number})", end="\r")
            c.execute(
                f"""
                SELECT fileID, relativePath, flags, file AS metadata,
                ROW_NUMBER() OVER(ORDER BY relativePath) AS _index
                FROM Files
                WHERE domain = '{_wts_id}'
                ORDER BY relativePath
                """
            )
            if not os.path.isdir(_wts_id):
                os.mkdir(_wts_id)

            row = c.fetchone()
            while row is not None:
                if not row["relativePath"]:  # Skip empty relative paths
                    row = c.fetchone()
                    continue

                destination = os.path.join(_wts_id, row["relativePath"])
                hashes = row["fileID"]
                folder = hashes[:2]
                flags = row["flags"]

                if flags == 2:  # Directory
                    try:
                        os.mkdir(destination)
                    except FileExistsError:
                        pass
                elif flags == 1:  # File
                    shutil.copyfile(os.path.join(self.base_dir, folder, hashes), destination)
                    metadata = BPListReader(row["metadata"]).parse()
                    creation = metadata["$objects"][1]["Birth"]
                    modification = metadata["$objects"][1]["LastModified"]
                    os.utime(destination, (modification, modification))

                if row["_index"] % 100 == 0:
                    print(f"Extracting WhatsApp files...({row['_index']}/{total_row_number})", end="\r")
                row = c.fetchone()
            print(f"Extracting WhatsApp files...({total_row_number}/{total_row_number})", end="\n")


def extract_media(base_dir, identifiers, decrypt_chunk_size):
    """
    Extracts WhatsApp data (media, messages, contacts, calls) from an iOS backup.

    Args:
        base_dir (str): The path to the iOS backup directory.
        identifiers (WhatsAppIdentifier): An object containing WhatsApp file identifiers.
        decrypt_chunk_size (int): The chunk size for decryption.
    """
    extractor = BackupExtractor(base_dir, identifiers, decrypt_chunk_size)
    extractor.extract()

