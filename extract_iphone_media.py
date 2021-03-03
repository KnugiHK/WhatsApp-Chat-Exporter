#!/usr/bin/python3

import shutil
import sqlite3
import os


def extract_media(base_dir):
    with sqlite3.connect(f"{base_dir}/Manifest.db") as manifest:
        c = manifest.cursor()
        c.execute("""SELECT count()
                    FROM Files
                    WHERE relativePath
                        LIKE 'Message/Media/%'""")
        total_row_number = c.fetchone()[0]
        print(f"Gathering media...(0/{total_row_number})", end="\r")
        c.execute("""SELECT fileID,
                            relativePath,
                            flags
                    FROM Files
                    WHERE relativePath
                        LIKE 'Message/Media/%'""")
        row = c.fetchone()
        if not os.path.isdir("Message"):
            os.mkdir("Message")
        if not os.path.isdir("Message/Media"):
            os.mkdir("Message/Media")
        i = 0
        while row is not None:
            destination = row[1]
            hashes = row[0]
            folder = hashes[:2]
            flags = row[2]
            if flags == 2:
                os.mkdir(destination)
            elif flags == 1:
                shutil.copyfile(f"{base_dir}/{folder}/{hashes}", destination)
            i += 1
            if i % 100 == 0:
                print(f"Gathering media...({i}/{total_row_number})", end="\r")
            row = c.fetchone()
        print(f"Gathering media...({total_row_number}/{total_row_number})", end="\r")


if __name__ == "__main__":
    from optparse import OptionParser
    parser = OptionParser()
    (_, args) = parser.parse_args()
    base_dir = args[0]
    extract_media(base_dir)
