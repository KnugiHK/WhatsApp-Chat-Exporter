"""
WhatsApp Poll decoder for iOS/macOS.

Decodes poll messages (ZMESSAGETYPE = 46) stored as protobuf blobs
in ZWAMESSAGEINFO.ZRECEIPTINFO. Uses raw varint/wire-type parsing
with no external protobuf library dependency.
"""

import struct


def _decode_varint(data, pos):
    """Decode a protobuf varint starting at pos.

    Args:
        data (bytes): The protobuf data.
        pos (int): Starting position.

    Returns:
        tuple: (value, new_pos)

    Raises:
        ValueError: If the varint is truncated.
    """
    result = 0
    shift = 0
    while pos < len(data):
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7
    raise ValueError("Truncated varint")


def decode_protobuf_fields(data):
    """
    Decode raw protobuf bytes into list of (field_number, wire_type_name, value).
    Handles: varint (0), fixed64 (1), length-delimited/bytes (2), fixed32 (5).

    Args:
        data (bytes): Raw protobuf data.

    Returns:
        list: List of (field_number, wire_type_name, value) tuples.
    """
    fields = []
    pos = 0
    while pos < len(data):
        try:
            tag, pos = _decode_varint(data, pos)
            field_num = tag >> 3
            wire_type = tag & 0x7

            if wire_type == 0:  # varint
                val, pos = _decode_varint(data, pos)
                fields.append((field_num, 'varint', val))
            elif wire_type == 2:  # length-delimited
                length, pos = _decode_varint(data, pos)
                val = data[pos:pos + length]
                pos += length
                fields.append((field_num, 'bytes', val))
            elif wire_type == 5:  # fixed32
                val = struct.unpack('<I', data[pos:pos + 4])[0]
                pos += 4
                fields.append((field_num, 'fixed32', val))
            elif wire_type == 1:  # fixed64
                val = struct.unpack('<Q', data[pos:pos + 8])[0]
                pos += 8
                fields.append((field_num, 'fixed64', val))
            else:
                break  # Unknown wire type, stop parsing
        except Exception:
            break
    return fields


def _decode_vote_record(data):
    """Decode a single vote record sub-message.

    Args:
        data (bytes): Raw protobuf data for a vote record.

    Returns:
        dict or None: Vote record with 'voter_jid' and 'selected_indices',
                      or None if the record is empty.
    """
    fields = decode_protobuf_fields(data)

    selected_indices = []
    voter_jid = None

    for fn, wt, val in fields:
        if fn == 1 and wt == 'varint':
            selected_indices.append(val)
        elif fn == 4 and wt == 'bytes':
            try:
                voter_jid = val.decode('utf-8')
            except Exception:
                voter_jid = val.hex()

    if not voter_jid and not selected_indices:
        return None

    return {
        'voter_jid': voter_jid,
        'selected_indices': selected_indices,
    }


def decode_poll_from_receipt_blob(receipt_blob):
    """
    Decode a WhatsApp poll from the ZWAMESSAGEINFO.ZRECEIPTINFO protobuf blob.

    The blob has a top-level structure where field 8 contains the poll content.
    The poll content has: question (field 2), options (field 3 repeated),
    other voters (field 5 repeated), and creator vote (field 6).

    Args:
        receipt_blob (bytes): The ZRECEIPTINFO protobuf blob.

    Returns:
        dict or None: Decoded poll data with keys:
            question (str): The poll question text
            options (list[str]): The poll option texts, in order
            votes (list[dict]): Each vote has:
                voter_jid (str|None): Voter's JID (LID format)
                selected_indices (list[int]): 0-based indices into options
                is_creator (bool): True if this is the poll creator's vote
        Returns None if the blob does not contain a valid poll.
    """
    if not receipt_blob:
        return None

    top_fields = decode_protobuf_fields(receipt_blob)

    # Find the poll content in field 8
    poll_content = None
    for fn, wt, val in top_fields:
        if fn == 8 and wt == 'bytes':
            poll_content = val
            break

    if not poll_content:
        return None

    poll_fields = decode_protobuf_fields(poll_content)

    # Extract question (field 2, first string)
    question = None
    for fn, wt, val in poll_fields:
        if fn == 2 and wt == 'bytes':
            try:
                question = val.decode('utf-8')
            except Exception:
                question = repr(val)
            break

    if not question:
        return None

    # Extract options (field 3, repeated)
    options = []
    for fn, wt, val in poll_fields:
        if fn == 3 and wt == 'bytes':
            option_fields = decode_protobuf_fields(val)
            for ofn, owt, oval in option_fields:
                if ofn == 1 and owt == 'bytes':
                    try:
                        options.append(oval.decode('utf-8'))
                    except Exception:
                        options.append(repr(oval))
                    break

    # Extract votes: field 5 = other participants, field 6 = creator
    votes = []
    for fn, wt, val in poll_fields:
        if fn in (5, 6) and wt == 'bytes':
            vote = _decode_vote_record(val)
            if vote:
                vote['is_creator'] = (fn == 6)
                votes.append(vote)

    return {
        'question': question,
        'options': options,
        'votes': votes,
    }
