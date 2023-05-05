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


# iOS Specific

APPLE_TIME = datetime.timestamp(datetime(2001, 1, 1))
