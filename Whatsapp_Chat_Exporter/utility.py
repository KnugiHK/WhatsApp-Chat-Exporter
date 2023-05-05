from bleach import clean as sanitize
from markupsafe import Markup
from datetime import datetime
from enum import Enum


def sanitize_except(html):
    return Markup(sanitize(html, tags=["br"]))


def determine_day(last, current):
    last = datetime.fromtimestamp(last).date()
    current = datetime.fromtimestamp(current).date()
    if last == current:
        return None
    else:
        return current


# Android Specific

CRYPT14_OFFSETS = (
    {"iv": 67, "db": 191},
    {"iv": 67, "db": 190},
    {"iv": 66, "db": 99},
    {"iv": 67, "db": 193}
)


class Crypt(Enum):
    CRYPT15 = 15
    CRYPT14 = 14
    CRYPT12 = 12


def brute_force_offset(max_iv=200, max_db=200):
    for iv in range(0, max_iv):
        for db in range(0, max_db):
            yield iv, iv + 16, db

def check_update():
    import urllib.request
    import json
    from sys import platform
    from .__init__ import __version__

    package_url_json = "https://pypi.org/pypi/whatsapp-chat-exporter/json"
    try:
        raw = urllib.request.urlopen(package_url_json)
    except Exception:
        print("Failed to check for updates.")
        return 1
    else:
        with raw:
            package_info = json.load(raw)
            latest_version = tuple(map(int, package_info["info"]["version"].split(".")))
            current_version = tuple(map(int, __version__.split(".")))
            if current_version < latest_version:
                print("===============Update===============")
                print("A newer version of WhatsApp Chat Exporter is available.")
                print("Current version: " + __version__)
                print("Latest version: " + package_info["info"]["version"])
                if platform == "win32":
                    print("Update with: pip install --upgrade whatsapp-chat-exporter")
                else:
                    print("Update with: pip3 install --upgrade whatsapp-chat-exporter")
                print("====================================")
            else:
                print("You are using the latest version of WhatsApp Chat Exporter.")
    return 0

# iOS Specific

APPLE_TIME = datetime.timestamp(datetime(2001, 1, 1))
