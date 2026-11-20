"""Small valid Unity Addressables catalogs and OBB archives for tests."""

import struct
import zipfile
from pathlib import Path

from quest_renamer.domain.operations import CancellationToken
from quest_renamer.infrastructure.addressables_catalog import CATALOG_ENTRY

DYNAMIC_FLAG = 0x40000000
CATALOG_VERSION = 2


class CatalogBuilder:
    def __init__(self) -> None:
        self.buffer = bytearray(32)
        self._strings: dict[tuple[str, bool], int] = {}
        self._dynamics: dict[tuple[str, ...], int] = {}

    def string(self, text: str, *, unicode: bool = False) -> int:
        key = (text, unicode)
        if key in self._strings:
            return self._strings[key]
        raw = text.encode("utf-16-le") if unicode else text.encode("utf-8")
        offset = len(self.buffer)
        self.buffer += struct.pack("<I", len(raw)) + raw
        string_id = offset + 4
        self._strings[key] = string_id
        return string_id

    def dynamic(self, components: list[str]) -> int:
        key = tuple(components)
        if key in self._dynamics:
            return self._dynamics[key]
        ids = [self.string(component) for component in reversed(components)]
        next_id = 0xFFFFFFFF
        head = 0
        for string_id in reversed(ids):
            offset = len(self.buffer)
            self.buffer += struct.pack("<II", string_id, next_id)
            next_id = offset
            head = offset
        root = head | DYNAMIC_FLAG
        self._dynamics[key] = root
        return root

    def record(self, string_id: int, next_id: int = 0xFFFFFFFF) -> int:
        offset = len(self.buffer)
        self.buffer += struct.pack("<II", string_id, next_id)
        return offset


def finish_catalog(builder: CatalogBuilder, internal_values: list[int]) -> bytes:
    data_offsets: list[int] = []
    for index, internal in enumerate(internal_values):
        primary = builder.string(f"key-{index}")
        provider = builder.string(
            "UnityEngine.ResourceManagement.ResourceProviders.AssetBundleProvider"
        )
        offset = len(builder.buffer)
        builder.buffer += struct.pack(
            "<7I", primary, internal, provider, 0xFFFFFFFF, 0, 0, 1
        )
        data_offsets.append(offset)
    builder.buffer += struct.pack("<I", len(data_offsets) * 4)
    set_offset = len(builder.buffer)
    builder.buffer += struct.pack(f"<{len(data_offsets)}I", *data_offsets)
    key_name = builder.string("catalog-key")
    keys_offset = len(builder.buffer) + 4
    builder.buffer += struct.pack("<I", 8)
    builder.buffer += struct.pack("<II", key_name, set_offset)
    struct.pack_into(
        "<8I",
        builder.buffer,
        0,
        0x0DE38942,
        CATALOG_VERSION,
        keys_offset,
        0,
        0,
        0,
        0,
        0,
    )
    return bytes(builder.buffer)


def build_catalog(chains: list[list[str]]) -> bytes:
    builder = CatalogBuilder()
    return finish_catalog(builder, [builder.dynamic(chain) for chain in chains])


def build_plain_catalog(internal_id: str) -> bytes:
    builder = CatalogBuilder()
    return finish_catalog(builder, [builder.string(internal_id)])


def write_obb(
    path: Path,
    catalog: bytes,
    *,
    compressed: bool = False,
    catalog_last: bool = False,
    comment: bytes = b"",
) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        if not catalog_last:
            archive.writestr("assets/aa/before.bin", b"before")
        archive.writestr(
            CATALOG_ENTRY,
            catalog,
            compress_type=(
                zipfile.ZIP_DEFLATED if compressed else zipfile.ZIP_STORED
            ),
        )
        if not catalog_last:
            archive.writestr("assets/aa/after.bin", b"after" * 4096)
        if comment:
            archive.comment = comment


class CancelOnCheck(CancellationToken):
    """Cancels itself on its ``cancel_at``-th ``raise_if_cancelled`` call."""

    def __init__(self, cancel_at: int) -> None:
        super().__init__()
        self.cancel_at = cancel_at
        self.calls = 0

    def raise_if_cancelled(self) -> None:
        self.calls += 1
        if self.calls >= self.cancel_at:
            self.cancel()
        super().raise_if_cancelled()


class CountingToken(CancellationToken):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def raise_if_cancelled(self) -> None:
        self.calls += 1
        super().raise_if_cancelled()
