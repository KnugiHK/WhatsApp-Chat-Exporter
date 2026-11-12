# `--split` Feature: Output Splitting

## Overview

The `--split` flag controls how chat exports are split across multiple HTML
files. It supports **time-based** splitting (monthly, quarterly, yearly) and
**size-based** splitting.

It replaces the old `--size` / `--output-size` flag, which is now **deprecated**
but still works. When both are given, `--split` takes precedence.

---

## Usage

```
--split [m|q|y|#K|#M|0]
```

| Value | Mode | Behaviour |
|-------|------|-----------|
| `m`   | time | Split by **calendar month** → each file contains one month |
| `q`   | time | Split by **calendar quarter** → each file contains Q1–Q4 |
| `y`   | time | Split by **calendar year** |
| `100K`| size | Split at ~100 KB per file |
| `2M`  | size | Split at ~2 MB per file |
| `10MB`| size | Split at ~10 MB per file (also accepts `KB`, `GB`) |
| `0`   | size | Auto-size (defaults to ~5 MB internally, same as old `--size 0`) |
| *(omitted)* | size | Same as `0` — bare `--split` with no argument defaults to auto-size |

### Examples

```bash
# Monthly split
wtsexporter -a --split m

# Quarterly split
wtsexporter -i --split q

# Yearly split
wtsexporter -a --split y

# Size-based: 500 KB per file
wtsexporter -i --split 500K

# Size-based: 2 MB per file
wtsexporter -a --split 2M

# Auto-size (legacy behaviour)
wtsexporter -a --split

# Old flag still works (deprecated)
wtsexporter -a --size 10MB
```

---

## Output file naming

### Time-based

Messages are grouped chronologically by period. Each group produces one HTML
file with a human-readable period suffix.

| Mode   | Pattern                      | Example (chat `Mom`)            |
|--------|------------------------------|----------------------------------|
| Month  | `<chatname>-YYYY-MM.html`    | `Mom-2026-01.html`               |
| Quarter| `<chatname>-YYYY-Q#.html`    | `Mom-2026-Q1.html`               |
| Year   | `<chatname>-YYYY.html`       | `Mom-2026.html`                  |

### Size-based

When the accumulated estimated HTML size of messages exceeds the threshold,
a new file is created. Files are numbered sequentially with zero-padded
two-digit suffixes.

| Pattern                         | Example                     |
|---------------------------------|-----------------------------|
| `<chatname>-part<NN>.html`      | `Mom-part01.html`           |

> Note: the old `--size` flag previously used `chatname-1.html` / `chatname-2.html`
> (no `part` prefix, no zero-padding). This has been changed to `-partNN` to avoid
> ambiguity with month numbers (`chatname-01.html` could mean January or part 1).

---

## Navigation between pages

All split files include **previous / next navigation links** in the HTML header.
- The first page has no previous link.
- The last page has no next link.
- The links use relative paths (e.g. `href="./Mom-2026-02.html"`) so the
  exported directory works when opened from a file browser or served via HTTP.

---

## Corner cases

### Empty periods

If a chat has messages only in Jan and Mar but not Feb, the `--split m` output
produces only two files: `-2026-01.html` and `-2026-03.html`. **No empty file
is created for February.** This is by design — only periods that actually
contain messages generate output.

### Single-period chats

A chat spanning only one month (or one quarter/year) with `--split m` still
produces a single file with the periodic suffix (e.g. `Mom-2026-01.html`)
for consistency with multi-period outputs. The suffix is always included;
it is never omitted for single-file edge cases.

### Messages with timestamp 0

If a message has `timestamp = 0` (Unix epoch), it is grouped under `1970-01`.
These messages will appear in their own file if they are the only ones in that
period, or alongside other January-1970 messages. This is a rare edge case
that typically indicates a corrupt or placeholder message.

### Backward compatibility with `--size`

`--size` is deprecated but not removed. When `--size` is used, it is
internally converted to the equivalent `("size", bytes)` tuple and processed
by the same code path. The only behavioural difference is the file naming:
`--size` now also produces `-partNN` files instead of bare numbers, so output
is consistent regardless of which flag is used.

### Interaction with `--date` filter

When `--date` is combined with `--split`, the date filter is applied first
during data extraction. Only messages within the filtered range are passed to
the split logic. This means `--split m` on a chat filtered to a single week
will produce exactly one file — the filter already reduced the
message set.

### Interaction with `--incremental-merge`

`--split` operates on the HTML generation stage, which runs after incremental
merge completes. The merge itself works on raw JSON data and is unaffected by
the split mode.

---

## Implementation details (for PR)

Two files were modified:

### `__main__.py`

- **New argument**: `--split` added to the `Output Options` group. Uses
  `nargs='?'` with `const="0"` so it accepts an optional value.
- **New helper** `parse_split_mode()`: converts the raw CLI value into a
  canonical tuple `(mode, value)`. `mode` is either `"time"` (for m/q/y)
  or `"size"` (for byte values). The function normalizes shorthand units —
  `100K` → `100KB`, `2M` → `2MB` — before delegating to the existing
  `readable_to_bytes()`.
- **Validation**: `--split` and `--size` are reconciled at validation time.
  If `--split` is given, it is parsed and stored in `args.split`. Otherwise
  `--size` is converted to `("size", bytes)` and stored in `args.split` as
  well. This means all downstream code reads a single attribute.
- **Three call sites** updated to pass `args.split` instead of `args.size`.

### `android_handler.py`

- **`create_html()` parameter**: renamed from `maximum_size` to `split_mode`.
  When `split_mode` is not `None`, it is unpacked as `(mode, value)` and
  dispatched to `_split_by_time()` or `_generate_paginated_chat()`.
- **`_generate_paginated_chat()`**: now generates `-partNN` filenames
  (e.g. `chat-part01.html`) instead of the old `-N` / bare-first-page scheme.
  The special case for `current_page == 1` that omitted the suffix was
  removed — every page consistently uses `-part{page:02d}`.
- **New function `_split_by_time()`**: iterates messages in order, groups
  them by calendar period (month/quarter/year), and renders one HTML file
  per group with correct prev/next navigation.
