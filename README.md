# Whatsapp-Chat-Exporter
A Whatsapp database parser that will give you the history of your Whatsapp conversations in HTML and JSON  
**If you plan to uninstall WhatsApp or delete your WhatsApp account, please make a backup of your WhatsApp database. You may want to use this exporter again on the same database in the future as the exporter develops**

# Usage
**If you want to use the old release of the exporter, please follow the [old usage guide](old_README.md#usage)**

First, clone this repo and install the exporter.
```shell
git clone https://github.com/KnugiHK/Whatsapp-Chat-Exporter.git
cd Whatsapp-Chat-Exporter
python setup.py install
```
Then, create a working directory in somewhere you want
```shell
mkdir working_wts
cd working_wts
```
## Working with Android
Extract the WhatsApp database with whatever means, one possible means is to use the [WhatsApp-Key-DB-Extractor](https://github.com/KnugiHK/WhatsApp-Key-DB-Extractor)

After you obtain your WhatsApp databse, copy the WatsApp database and media folder to the working directory. The database is called msgstore.db. If you also want the name of your contacts, get the contact database, which is called wa.db. And copy the WhatsApp (Media) directory from your phone directly.

And now, you should have something like this in the working directory.

![Android folder structure](imgs/android_structure.png)
### Extracting
Simply invoke the following command from shell, remember to replace the username and device id correspondingly in the command.
```sh
wtsexporter -a
```

## Working with iPhone
Do an iPhone Backup with iTunes first.
### Encrypted iPhone Backup
**If you are working on unencrypted iPhone backup, skip this**

If you want to work on an encrypted iPhone Backup, you should install iphone_backup_decrypt from [KnugiHK/iphone_backup_decrypt](https://github.com/KnugiHK/iphone_backup_decrypt) before you run the extract_iphone_media.py.
```sh
pip install biplist pycryptodome & :: Optional, since the pip will install these dependencies automatically.
pip install git+https://github.com/KnugiHK/iphone_backup_decrypt
```
### Extracting
Simply invoke the following command from shell, remember to replace the username and device id correspondingly in the command.
```sh
wtsexporter -i -b "C:\Users\[Username]\AppData\Roaming\Apple Computer\MobileSync\Backup\[device id]"
```

## Results
After extracting, you will get these:
#### Private Message
![Private Message](imgs/pm.png)

#### Group Message
![Group Message](imgs/group.png)

## More options
Invoke the wtsexporter with --help option will show you all options available.
```sh
> wtsexporter --help
Usage: wtsexporter [options]

Options:
  --version             show program's version number and exit
  -h, --help            show this help message and exit
  -a, --android         Define the target as Android
  -i, --iphone          Define the target as iPhone
  -w WA, --wa=WA        Path to contact database
  -m MEDIA, --media=MEDIA
                        Path to WhatsApp media folder
  -b BACKUP, --backup=BACKUP
                        Path to iPhone backup
  -o OUTPUT, --output=OUTPUT
                        Output to specific directory
  -j, --json            Save the result to a single JSON file
  -d DB, --db=DB        Path to database file
```

# To do
1. Convert ```\r\n``` to ```<br>```
2. Reply in iPhone
3. The CSS for metadata (e.g. {Message Deleted})
4. Handle encrypted iPhone Backup

# Copyright
This is a MIT licensed project.

The Telegram Desktop's export is the reference for whatsapp.html in this repo
