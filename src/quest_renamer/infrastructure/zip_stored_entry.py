"""In-place rewrite of one STORED entry of a ZIP archive.

Package-agnostic toolkit. Only plain archives are handled: the entry must be
STORED, must not use a data descriptor, and the archive must not be ZIP64 or
multi-disk. Anything else is refused. The bytes after the entry are shifted by
the size difference, the entry's headers and the central directory are patched,
and the result is verified by reading the archive back.
"""

from __future__ import annotations

import os
import struct
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from quest_renamer.domain.operations import CancellationToken

_COPY_BLOCK = 8 * 1024 * 1024

_EOCD_SIGNATURE = 0x06054B50
_CENTRAL_SIGNATURE = 0x02014B50
_LOCAL_SIGNATURE = 0x04034B50
_EOCD_SIZE = 22
_MAX_COMMENT = 0xFFFF
_U32_LIMIT = 0xFFFFFFFF

_LOCAL_HEADER = struct.Struct("<IHHHHHIIIHH")
_CENTRAL_ENTRY = struct.Struct("<IHHHHHHIIIHHHHHII")
_EOCD = struct.Struct("<IHHHHIIH")


class ZipStoredEntryError(ValueError):
    """A ZIP entry could not be rewritten safely."""


def _unpack(structure: struct.Struct, data: bytes | bytearray, offset: int) -> tuple[int, ...]:
    if offset < 0 or offset + structure.size > len(data):
        raise ZipStoredEntryError("the archive contains an out-of-range offset.")
    return tuple(int(value) for value in structure.unpack_from(data, offset))


def rewrite_stored_entry(
    archive_path: Path,
    entry_name: str,
    payload: bytes,
    *,
    token: CancellationToken,
) -> int:
    """Replace one STORED entry's data in place and verify the archive.

    Returns the size change in bytes. Cancellation during the rewrite leaves the
    archive unusable, so callers must discard the file in that case.
    """
    try:
        with zipfile.ZipFile(archive_path) as archive:
            info = archive.getinfo(entry_name)
    except zipfile.BadZipFile as exc:
        raise ZipStoredEntryError(
            f"{archive_path.name} is not a readable archive ({exc})."
        ) from exc
    except KeyError as exc:
        raise ZipStoredEntryError(
            f"{archive_path.name} has no {entry_name} entry."
        ) from exc
    token.raise_if_cancelled()
    _rewrite_stored_entry(archive_path, entry_name, info, payload, token)
    token.raise_if_cancelled()
    _verify_rewritten_entry(archive_path, entry_name, payload)
    return len(payload) - info.file_size


@dataclass(frozen=True, slots=True)
class _EndOfCentralDirectory:
    offset: int
    cd_offset: int
    cd_size: int
    entries: int
    raw: bytes



def _read_exact(handle: BinaryIO, offset: int, size: int) -> bytes:
    if offset < 0 or size < 0:
        raise ZipStoredEntryError("the archive has an invalid offset.")
    handle.seek(offset)
    data = handle.read(size)
    if len(data) != size:
        raise ZipStoredEntryError("the archive ended unexpectedly.")
    return data


def _read_eocd(handle: BinaryIO, size: int) -> _EndOfCentralDirectory:
    start = max(0, size - (_EOCD_SIZE + _MAX_COMMENT))
    tail = _read_exact(handle, start, size - start)
    signature = struct.pack("<I", _EOCD_SIGNATURE)
    index = tail.rfind(signature)
    while index >= 0:
        if index + _EOCD_SIZE <= len(tail):
            fields = _unpack(_EOCD, tail, index)
            comment_length = fields[7]
            if index + _EOCD_SIZE + comment_length == len(tail):
                disk, cd_disk, entries_disk, entries, cd_size, cd_offset = fields[1:7]
                if disk or cd_disk or entries_disk != entries:
                    raise ZipStoredEntryError(
                        "multi-disk archives are not supported."
                    )
                if (
                    entries == 0xFFFF
                    or cd_size == _U32_LIMIT
                    or cd_offset == _U32_LIMIT
                ):
                    raise ZipStoredEntryError(
                        "ZIP64 archives are not rewritten in place."
                    )
                if cd_offset + cd_size > size:
                    raise ZipStoredEntryError(
                        "the central directory is outside the file."
                    )
                return _EndOfCentralDirectory(
                    offset=start + index,
                    cd_offset=cd_offset,
                    cd_size=cd_size,
                    entries=entries,
                    raw=tail[index : index + _EOCD_SIZE + comment_length],
                )
        index = tail.rfind(signature, 0, index)
    raise ZipStoredEntryError("the archive has no central directory.")


def _rewrite_stored_entry(
    archive: Path,
    entry_name: str,
    info: zipfile.ZipInfo,
    payload: bytes,
    token: CancellationToken,
) -> None:
    with archive.open("r+b") as handle:
        size = handle.seek(0, os.SEEK_END)
        local = _unpack(
            _LOCAL_HEADER, _read_exact(handle, info.header_offset, _LOCAL_HEADER.size), 0
        )
        signature, _version, flags, method, _time, _date, _crc, csize, usize = local[:9]
        name_length, extra_length = local[9], local[10]
        if signature != _LOCAL_SIGNATURE:
            raise ZipStoredEntryError(
                f"{archive.name} has no local header for {entry_name}."
            )
        if method != zipfile.ZIP_STORED:
            raise ZipStoredEntryError(
                f"{archive.name} stores {entry_name} compressed; that layout is not "
                "rewritten automatically."
            )
        if flags & 0x8:
            raise ZipStoredEntryError(
                f"{archive.name} uses a data descriptor for {entry_name}; that layout "
                "is not rewritten automatically."
            )
        if csize != info.file_size or usize != info.file_size:
            raise ZipStoredEntryError(
                f"{archive.name} reports inconsistent sizes for {entry_name}."
            )
        data_offset = info.header_offset + _LOCAL_HEADER.size + name_length
        data_offset += extra_length
        insert = data_offset + info.file_size
        if insert > size:
            raise ZipStoredEntryError(
                f"the {entry_name} entry in {archive.name} is outside the file."
            )
        eocd = _read_eocd(handle, size)
        if eocd.cd_offset < insert:
            raise ZipStoredEntryError(
                "the central directory overlaps the rewritten entry."
            )
        central = bytearray(
            _read_exact(handle, eocd.cd_offset, eocd.cd_size)
        )
        delta = len(payload) - info.file_size
        _shift_region(handle, insert, eocd.cd_offset, delta, token)
        handle.seek(data_offset)
        handle.write(payload)
        crc = zlib.crc32(payload) & 0xFFFFFFFF
        handle.seek(info.header_offset + 14)
        handle.write(struct.pack("<III", crc, len(payload), len(payload)))
        _patch_central_directory(
            central,
            entry_header_offset=info.header_offset,
            cd_offset=eocd.cd_offset,
            insert=insert,
            delta=delta,
            entries=eocd.entries,
            size=len(payload),
            crc=crc,
        )
        central_offset = eocd.cd_offset + delta
        handle.seek(central_offset)
        handle.write(central)
        eocd_raw = bytearray(eocd.raw)
        struct.pack_into("<I", eocd_raw, 16, central_offset)
        handle.seek(eocd.offset + delta)
        handle.write(eocd_raw)
        handle.truncate(size + delta)


def _shift_region(
    handle: BinaryIO, start: int, end: int, delta: int, token: CancellationToken
) -> None:
    if delta == 0 or end <= start:
        return
    remaining = end - start
    if delta > 0:
        while remaining > 0:
            token.raise_if_cancelled()
            chunk = min(_COPY_BLOCK, remaining)
            source = start + remaining - chunk
            block = _read_exact(handle, source, chunk)
            handle.seek(source + delta)
            handle.write(block)
            remaining -= chunk
        return
    position = start
    while position < end:
        token.raise_if_cancelled()
        chunk = min(_COPY_BLOCK, end - position)
        block = _read_exact(handle, position, chunk)
        handle.seek(position + delta)
        handle.write(block)
        position += chunk


def _patch_central_directory(
    central: bytearray,
    *,
    entry_header_offset: int,
    cd_offset: int,
    insert: int,
    delta: int,
    entries: int,
    size: int,
    crc: int,
) -> None:
    position = 0
    counted = 0
    while position < len(central):
        fields = list(_unpack(_CENTRAL_ENTRY, central, position))
        if fields[0] != _CENTRAL_SIGNATURE:
            raise ZipStoredEntryError(
                "the central directory contains an unexpected entry."
            )
        name_length, extra_length, comment_length = fields[10], fields[11], fields[12]
        local_offset = fields[16]
        if local_offset < 0 or local_offset >= cd_offset:
            raise ZipStoredEntryError(
                "the central directory points outside the file."
            )
        if local_offset == entry_header_offset:
            fields[7], fields[8], fields[9] = crc, size, size
        elif local_offset >= insert:
            fields[16] = local_offset + delta
        _CENTRAL_ENTRY.pack_into(central, position, *fields)
        position += _CENTRAL_ENTRY.size + name_length + extra_length + comment_length
        counted += 1
    if position != len(central) or counted != entries:
        raise ZipStoredEntryError("the central directory size is inconsistent.")


def _verify_rewritten_entry(path: Path, entry: str, payload: bytes) -> None:
    try:
        with path.open("rb") as handle, zipfile.ZipFile(handle) as archive:
            try:
                info = archive.getinfo(entry)
            except KeyError as exc:
                raise ZipStoredEntryError(
                    f"{entry} disappeared from the rewritten archive."
                ) from exc
            if info.compress_size != len(payload) or info.file_size != len(payload):
                raise ZipStoredEntryError(
                    "the rewritten archive reports the wrong entry size."
                )
            if archive.read(entry) != payload:
                raise ZipStoredEntryError(
                    "the rewritten archive does not contain the expected entry."
                )
            for candidate in archive.infolist():
                local = _unpack(
                    _LOCAL_HEADER,
                    _read_exact(handle, candidate.header_offset, _LOCAL_HEADER.size),
                    0,
                )
                if local[0] != _LOCAL_SIGNATURE:
                    raise ZipStoredEntryError(
                        "the rewritten archive has an invalid local header for "
                        f"{candidate.filename}."
                    )
    except zipfile.BadZipFile as exc:
        raise ZipStoredEntryError(
            f"the rewritten archive could not be verified ({exc})."
        ) from exc
