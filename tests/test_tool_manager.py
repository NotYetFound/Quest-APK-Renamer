import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request

from quest_renamer.domain.operations import CancellationToken, OperationCancelled
from quest_renamer.infrastructure.tool_manager import (
    PinnedToolManager,
    ToolRepairError,
    _default_open,
)


class FakeResponse(io.BytesIO):
    def __init__(self, payload: bytes, on_read: object = None) -> None:
        super().__init__(payload)
        self.headers = {"Content-Length": str(len(payload))}
        self._on_read = on_read

    def read(self, size: int = -1) -> bytes:
        chunk = super().read(size)
        if chunk and callable(self._on_read):
            self._on_read()
            self._on_read = None
        return chunk


class ToolManagerTests(unittest.TestCase):
    def test_default_opener_uses_shared_trusted_https(self) -> None:
        response = FakeResponse(b"tool")
        request = Request("https://example.invalid/tool")
        with patch(
            "quest_renamer.infrastructure.trusted_https.trusted_urlopen",
            return_value=response,
        ) as opened:
            returned = _default_open(request, 12.0)

        self.assertIs(returned, response)
        opened.assert_called_once_with(request, 12.0)

    def _manager(
        self,
        root: Path,
        *,
        payloads: dict[str, bytes],
        opener_payloads: dict[str, bytes] | None = None,
        on_read: object = None,
    ) -> PinnedToolManager:
        resources = root / "resources"
        resources.mkdir()
        catalog = {
            "apktool": {
                "file": "apktool.jar",
                "version": "1.2.3",
                "url": "https://example.invalid/apktool.jar",
                "sha256": hashlib.sha256(payloads["apktool"]).hexdigest(),
            },
            "uber_apk_signer": {
                "file": "signer.jar",
                "version": "4.5.6",
                "url": "https://example.invalid/signer.jar",
                "sha256": hashlib.sha256(payloads["signer"]).hexdigest(),
            },
        }
        catalog_path = resources / "toolchain.json"
        catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
        downloads = opener_payloads if opener_payloads is not None else payloads

        def opener(request: Request, timeout: float) -> FakeResponse:
            self.assertEqual(timeout, 30.0)
            key = "apktool" if request.full_url.endswith("apktool.jar") else "signer"
            return FakeResponse(downloads[key], on_read=on_read)

        return PinnedToolManager(
            catalog_path=catalog_path,
            resource_root=root,
            data_root=root / "data",
            environment={},
            opener=opener,
        )

    def test_downloads_verifies_and_records_missing_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payloads = {"apktool": b"apktool-data", "signer": b"signer-data"}
            manager = self._manager(root, payloads=payloads)
            updates: list[tuple[float, str]] = []

            result = manager.repair_all(
                progress=lambda value, text: updates.append((value, text))
            )

            self.assertTrue(result.snapshot.all_ready)
            self.assertEqual(result.repaired, ("apktool", "uber_apk_signer"))
            self.assertEqual(
                (manager.managed_root / "apktool.jar").read_bytes(), b"apktool-data"
            )
            manifest = json.loads((manager.managed_root / "versions.json").read_text())
            self.assertEqual(manifest["apktool"]["version"], "1.2.3")
            self.assertEqual(updates[-1], (1.0, "Android tools are ready"))

    def test_valid_files_are_not_downloaded_again(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payloads = {"apktool": b"apktool-data", "signer": b"signer-data"}
            manager = self._manager(root, payloads=payloads)
            manager.managed_root.mkdir(parents=True)
            (manager.managed_root / "apktool.jar").write_bytes(payloads["apktool"])
            (manager.managed_root / "signer.jar").write_bytes(payloads["signer"])

            result = manager.repair_all()

            self.assertEqual(result.repaired, ())
            self.assertTrue(result.snapshot.all_ready)

    def test_bad_checksum_is_discarded_without_overwriting_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payloads = {"apktool": b"expected", "signer": b"signer-data"}
            manager = self._manager(
                root,
                payloads=payloads,
                opener_payloads={"apktool": b"wrong", "signer": b"signer-data"},
            )
            manager.managed_root.mkdir(parents=True)
            destination = manager.managed_root / "apktool.jar"
            destination.write_bytes(b"old-damaged-copy")

            with self.assertRaisesRegex(ToolRepairError, "pinned SHA-256"):
                manager.repair_all()

            self.assertEqual(destination.read_bytes(), b"old-damaged-copy")
            self.assertEqual(list(manager.managed_root.glob("*.download")), [])

    def test_cancellation_removes_partial_download_and_keeps_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            token = CancellationToken()
            payloads = {"apktool": b"a" * 400_000, "signer": b"signer-data"}
            manager = self._manager(root, payloads=payloads, on_read=token.cancel)
            manager.managed_root.mkdir(parents=True)
            destination = manager.managed_root / "apktool.jar"
            destination.write_bytes(b"old-damaged-copy")

            with self.assertRaises(OperationCancelled):
                manager.repair_all(token=token)

            self.assertEqual(destination.read_bytes(), b"old-damaged-copy")
            self.assertEqual(list(manager.managed_root.glob("*.download")), [])


if __name__ == "__main__":
    unittest.main()
