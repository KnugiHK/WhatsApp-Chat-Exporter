#!/usr/bin/python3

import shutil
import sqlite3
import os

manifest = sqlite3.connect(f"{sys.argv[2]}/Manifest.db")
c = manifest.cursor()
c.execute("""SELECT count() FROM Files WHERE relativePath LIKE 'Message/Media/%'""")
total_row_number = c.fetchone()[0]
print(f"Gathering media...(0/{total_row_number})", end="\r")
c.execute("""SELECT fileID, relativePath, flags FROM Files WHERE relativePath LIKE 'Message/Media/%'""")
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
        shutil.copyfile(f"{sys.argv[2]}/{folder}/{hashes}", destination)
    i += 1
    if i % 100 == 0:
        print(f"Gathering media...({i}/{total_row_number})", end="\r")
    row = c.fetchone()
print(f"Gathering media...({total_row_number}/{total_row_number})", end="\r")
manifest.close()