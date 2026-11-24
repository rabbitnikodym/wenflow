"""A small reader for Kindle MOBI / AZW / AZW3 / PRC files: (title, author, markup).

Only what a book import needs: the PalmDB container, the MOBI header, PalmDOC decompression and the
EXTH metadata block. Copy-protected files are refused, not unlocked.
"""
from __future__ import annotations

import struct


class MobiError(ValueError):
    pass


def _palmdoc(data: bytes) -> bytes:
    """PalmDOC (LZ77) decompression of one text record."""
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        c = data[i]
        i += 1
        if c == 0 or 9 <= c <= 0x7F:
            out.append(c)
        elif c <= 8:
            out += data[i:i + c]
            i += c
        elif c >= 0xC0:
            out.append(0x20)
            out.append(c ^ 0x80)
        elif i < n:
            c = (c << 8) | data[i]
            i += 1
            dist, length = (c >> 3) & 0x7FF, (c & 7) + 3
            if 0 < dist <= len(out):
                for _ in range(length):
                    out.append(out[-dist])
    return bytes(out)


def _trailing(rec: bytes, flags: int) -> int:
    """Bytes of bookkeeping appended to a text record (index data, split multi-byte characters)."""
    size = len(rec)
    num = 0
    rest = flags >> 1
    while rest:
        if rest & 1:
            pos, shift, val = size - num, 0, 0
            while pos > 0:
                v = rec[pos - 1]
                val |= (v & 0x7F) << shift
                shift += 7
                pos -= 1
                if v & 0x80 or shift >= 28:
                    break
            num += val
        rest >>= 1
    if flags & 1 and size - num - 1 >= 0:
        num += (rec[size - num - 1] & 0x3) + 1
    return min(num, size)


def _exth(rec0: bytes, start: int, codec: str) -> dict[int, str]:
    out: dict[int, str] = {}
    if rec0[start:start + 4] != b"EXTH":
        return out
    count = struct.unpack(">I", rec0[start + 8:start + 12])[0]
    pos = start + 12
    for _ in range(count):
        if pos + 8 > len(rec0):
            break
        kind, size = struct.unpack(">II", rec0[pos:pos + 8])
        if size < 8:
            break
        if kind in (100, 503) and kind not in out:
            out[kind] = rec0[pos + 8:pos + size].decode(codec, errors="ignore").strip()
        pos += size
    return out


def read(data: bytes) -> tuple[str, str, str]:
    """(title, author, markup) for a MOBI-family file. The markup is HTML with Kindle extras."""
    if len(data) < 80 or data[60:68] not in (b"BOOKMOBI", b"TEXtREAd"):
        raise MobiError("this is not a MOBI file")
    n = struct.unpack(">H", data[76:78])[0]
    offs = [struct.unpack(">I", data[78 + 8 * i:82 + 8 * i])[0] for i in range(n)] + [len(data)]
    if n < 2:
        raise MobiError("the file is empty")

    def record(i: int) -> bytes:
        return data[offs[i]:offs[i + 1]]

    rec0 = record(0)
    compression, _, _text_len, text_records, _rec_size, encryption = struct.unpack(">HHIHHH", rec0[:14])
    if encryption:
        raise MobiError("this copy is copy-protected (DRM), so it cannot be read here")
    if compression == 17480:
        raise MobiError("this file uses Huffman compression; convert it to EPUB (for example with Calibre) and import that")
    if compression not in (1, 2):
        raise MobiError(f"unknown compression type {compression}")

    codec, flags, title, author = "cp1252", 0, "", ""
    if rec0[16:20] == b"MOBI":
        header_len, _kind, codepage = struct.unpack(">III", rec0[20:32])
        codec = "utf-8" if codepage == 65001 else "cp1252"
        if header_len >= 0xE4 and len(rec0) >= 0xF4:
            flags = struct.unpack(">H", rec0[0xF2:0xF4])[0]
        name_off, name_len = struct.unpack(">II", rec0[0x54:0x5C])
        title = rec0[name_off:name_off + name_len].decode(codec, errors="ignore").strip()
        if struct.unpack(">I", rec0[0x80:0x84])[0] & 0x40:
            meta = _exth(rec0, 16 + header_len, codec)
            title = meta.get(503) or title
            author = meta.get(100, "")
    else:
        title = data[:32].split(b"\0")[0].decode("cp1252", errors="ignore")

    parts = []
    for i in range(1, min(text_records, n - 1) + 1):
        rec = record(i)
        rec = rec[:len(rec) - _trailing(rec, flags)]
        parts.append(_palmdoc(rec) if compression == 2 else rec)
    return title, author, b"".join(parts).decode(codec, errors="ignore")
