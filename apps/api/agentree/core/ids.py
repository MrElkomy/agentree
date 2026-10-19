"""Identifier helpers."""

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    """Time-ordered UUID (RFC 9562 version 7): index-friendly and not guessable."""
    unix_ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")
    value = (unix_ms & 0xFFFF_FFFF_FFFF) << 80
    value |= 0x7 << 76  # version
    value |= ((rand >> 62) & 0xFFF) << 64  # rand_a (12 bits)
    value |= 0b10 << 62  # variant
    value |= rand & 0x3FFF_FFFF_FFFF_FFFF  # rand_b (62 bits)
    return uuid.UUID(int=value)
