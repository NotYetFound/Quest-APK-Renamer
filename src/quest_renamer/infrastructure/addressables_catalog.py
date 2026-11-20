"""Reader and path rewriter for Unity Addressables v2 binary catalogs.

Package-agnostic toolkit: callers pass the old and new strings. New strings are
appended instead of moving existing bytes, so every other catalog offset stays
valid, and any layout this module does not fully understand is refused rather
than guessed at.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

CATALOG_ENTRY = "assets/aa/catalog.bin"
CATALOG_MAGIC = 0x0DE38942

_DYNAMIC_END = 0xFFFFFFFF
_DYNAMIC_FLAG = 0x40000000
_ID_MASK = 0x3FFFFFFF
_UNICODE_FLAG = 0x80000000
_U32_LIMIT = 0xFFFFFFFF

_U32 = struct.Struct("<I")
_HEADER = struct.Struct("<8I")
_DATA = struct.Struct("<7I")
_DYNAMIC_STRING = struct.Struct("<II")
_KEY = struct.Struct("<II")


class AddressablesCatalogError(ValueError):
    """An Addressables catalog could not be read or rewritten safely."""


@dataclass(frozen=True, slots=True)
class CatalogPatch:
    data: bytes
    repointed_records: int
    internal_ids: int


def _unpack(structure: struct.Struct, data: bytes | bytearray, offset: int) -> tuple[int, ...]:
    if offset < 0 or offset + structure.size > len(data):
        raise AddressablesCatalogError(
            "the Addressables catalog contains an out-of-range offset."
        )
    return tuple(int(value) for value in structure.unpack_from(data, offset))


class AddressablesCatalog:
    """Minimal reader for the Addressables v2 binary catalog layout."""

    def __init__(self, data: bytes) -> None:
        if len(data) < _HEADER.size:
            raise AddressablesCatalogError("the Addressables catalog is too short.")
        fields = _unpack(_HEADER, data, 0)
        if fields[0] != CATALOG_MAGIC:
            raise AddressablesCatalogError(
                "the Addressables catalog has an unexpected signature."
            )
        self.data = data
        self.keys_offset = fields[2]

    def u32(self, offset: int) -> int:
        return _unpack(_U32, self.data, offset)[0]

    def string(self, string_id: int) -> str:
        offset = string_id & _ID_MASK
        length = self.u32(offset - 4)
        raw = _unpack_length(self.data, offset, length)
        if string_id & _UNICODE_FLAG:
            try:
                return raw.decode("utf-16-le")
            except UnicodeDecodeError as exc:
                raise AddressablesCatalogError(
                    "the Addressables catalog contains malformed UTF-16 text."
                ) from exc
        return raw.decode("utf-8", "surrogateescape")

    def resolve(self, string_id: int, separator: str) -> str:
        if string_id == _DYNAMIC_END:
            raise AddressablesCatalogError(
                "the Addressables catalog refers to a missing string."
            )
        if not string_id & _DYNAMIC_FLAG:
            return self.string(string_id)
        components: list[str] = []
        seen: set[int] = set()
        current = string_id
        while True:
            offset = current & _ID_MASK
            if offset in seen:
                raise AddressablesCatalogError(
                    "the Addressables catalog contains a cyclic string chain."
                )
            seen.add(offset)
            component_id, next_id = _unpack(_DYNAMIC_STRING, self.data, offset)
            if component_id & _DYNAMIC_FLAG:
                raise AddressablesCatalogError(
                    "the Addressables catalog contains a nested dynamic string."
                )
            components.append(self.string(component_id))
            if next_id == _DYNAMIC_END:
                break
            current = next_id
        return separator.join(reversed(components))

    def records(self) -> tuple[_Location, ...]:
        size = self.u32(self.keys_offset - 4)
        if size % _KEY.size:
            raise AddressablesCatalogError(
                "the Addressables catalog has a malformed key table."
            )
        seen_sets: set[int] = set()
        records: list[_Location] = []
        for index in range(size // _KEY.size):
            _key_name_id, set_offset = _unpack(
                _KEY, self.data, self.keys_offset + index * _KEY.size
            )
            if set_offset in seen_sets:
                continue
            seen_sets.add(set_offset)
            set_size = self.u32(set_offset - 4)
            if set_size % 4:
                raise AddressablesCatalogError(
                    "the Addressables catalog has a malformed location set."
                )
            for position in range(0, set_size, 4):
                data_offset = self.u32(set_offset + position)
                fields = _unpack(_DATA, self.data, data_offset)
                records.append(
                    _Location(
                        primary_key=self.resolve(fields[0], "/"),
                        internal_id=self.resolve(fields[1], "/"),
                        provider=self.resolve(fields[2], "."),
                        internal_id_value=fields[1],
                    )
                )
        return tuple(records)


@dataclass(frozen=True, slots=True)
class _Location:
    primary_key: str
    internal_id: str
    provider: str
    internal_id_value: int


def _unpack_length(data: bytes | bytearray, offset: int, length: int) -> bytes:
    if offset < 0 or length < 0 or offset + length > len(data):
        raise AddressablesCatalogError(
            "the Addressables catalog contains an out-of-range string."
        )
    return bytes(data[offset : offset + length])


def resolve_catalog_internal_ids(data: bytes) -> tuple[str, ...]:
    """Return every resolved internal ID in an Addressables binary catalog."""
    return tuple(record.internal_id for record in AddressablesCatalog(data).records())


def rewrite_catalog_paths(
    data: bytes, old_package: str, new_package: str
) -> CatalogPatch | None:
    """Repoint the catalog's package component; ``None`` when nothing matches.

    Only the package segment changes: expansion-file version tags such as
    ``main.<tag>.<package>.obb`` are never matched or rewritten. The replacement
    string is appended at the end of the catalog and the shared dynamic-string
    record that names the old package is repointed to it. The abandoned bytes
    stay in place as unreferenced data.
    """
    if old_package == new_package:
        return None
    catalog = AddressablesCatalog(data)
    locations = catalog.records()
    affected: list[_Location] = []
    seen_ids: set[int] = set()
    for location in locations:
        if old_package not in location.internal_id:
            continue
        if location.internal_id_value in seen_ids:
            continue
        seen_ids.add(location.internal_id_value)
        affected.append(location)
    if not affected:
        return None
    replacement = new_package.encode("ascii")
    appended = struct.pack("<I", len(replacement)) + replacement
    if len(data) + len(appended) > _U32_LIMIT:
        raise AddressablesCatalogError(
            "the Addressables catalog is too large to append a replacement string."
        )
    new_id = len(data) + 4
    patched = bytearray(data)
    patched.extend(appended)
    repointed: set[int] = set()
    for location in affected:
        if not location.internal_id_value & _DYNAMIC_FLAG:
            raise AddressablesCatalogError(
                f"{old_package!r} appears inside a single stored internal ID; "
                "that layout is not rewritten automatically."
            )
        current = location.internal_id_value
        seen: set[int] = set()
        while True:
            offset = current & _ID_MASK
            if offset in seen:
                raise AddressablesCatalogError(
                    "the Addressables catalog contains a cyclic string chain."
                )
            seen.add(offset)
            component_id, next_id = _unpack(_DYNAMIC_STRING, patched, offset)
            if offset not in repointed:
                if component_id & _DYNAMIC_FLAG:
                    raise AddressablesCatalogError(
                        "the Addressables catalog contains a nested dynamic string."
                    )
                component = catalog.string(component_id)
                if component == old_package:
                    struct.pack_into("<I", patched, offset, new_id)
                    repointed.add(offset)
                elif old_package in component:
                    raise AddressablesCatalogError(
                        f"{old_package!r} appears inside a longer catalog string; "
                        "that layout is not rewritten automatically."
                    )
            if next_id == _DYNAMIC_END:
                break
            current = next_id
    if not repointed:
        raise AddressablesCatalogError(
            "the Addressables catalog did not expose the old package as a "
            "dynamic string component."
        )
    result = CatalogPatch(bytes(patched), len(repointed), len(affected))
    _verify_catalog_patch(catalog, result, old_package, new_package)
    return result


def _verify_catalog_patch(
    before: AddressablesCatalog,
    patch: CatalogPatch,
    old_package: str,
    new_package: str,
) -> None:
    expected = sorted(
        (
            location.primary_key,
            location.internal_id.replace(old_package, new_package),
            location.provider,
        )
        for location in before.records()
    )
    after = AddressablesCatalog(patch.data)
    actual = sorted(
        (location.primary_key, location.internal_id, location.provider)
        for location in after.records()
    )
    if actual != expected:
        raise AddressablesCatalogError(
            "the rewritten Addressables catalog did not resolve to the expected paths."
        )
