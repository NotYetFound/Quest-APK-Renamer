import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quest_renamer.domain.operations import CancellationToken
from quest_renamer.infrastructure.older_firmware_patch import (
    LOADER_RELATIVE,
    OlderFirmwarePatchError,
    apply_older_firmware_patch,
    verified_older_firmware_asset,
)


class OlderFirmwarePatchTests(unittest.TestCase):
    def test_verified_asset_replaces_only_an_existing_arm64_loader(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            decoded = root / "decoded"
            target = decoded / LOADER_RELATIVE
            target.parent.mkdir(parents=True)
            target.write_bytes(b"original loader")
            replacement = root / "replacement.so"
            replacement.write_bytes(b"verified replacement")
            expected = hashlib.sha256(replacement.read_bytes()).hexdigest()

            with patch(
                "quest_renamer.infrastructure.older_firmware_patch.LOADER_SHA256",
                expected,
            ):
                apply_older_firmware_patch(
                    decoded,
                    replacement,
                    token=CancellationToken(),
                )

            self.assertEqual(target.read_bytes(), replacement.read_bytes())

    def test_patch_never_injects_a_loader_into_an_apk_without_one(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            decoded = root / "decoded"
            decoded.mkdir()
            replacement = root / "replacement.so"
            replacement.write_bytes(b"verified replacement")
            expected = hashlib.sha256(replacement.read_bytes()).hexdigest()

            with (
                patch(
                    "quest_renamer.infrastructure.older_firmware_patch.LOADER_SHA256",
                    expected,
                ),
                self.assertRaisesRegex(
                    OlderFirmwarePatchError,
                    "does not contain an ARM64 Oculus platform loader",
                ),
            ):
                apply_older_firmware_patch(
                    decoded,
                    replacement,
                    token=CancellationToken(),
                )

            self.assertFalse((decoded / LOADER_RELATIVE).exists())

    def test_asset_availability_requires_the_exact_pinned_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            replacement = Path(temporary) / "replacement.so"
            replacement.write_bytes(b"verified replacement")
            expected = hashlib.sha256(replacement.read_bytes()).hexdigest()
            with patch(
                "quest_renamer.infrastructure.older_firmware_patch.LOADER_SHA256",
                expected,
            ):
                self.assertEqual(verified_older_firmware_asset(replacement), replacement)
            replacement.write_bytes(b"damaged")
            self.assertIsNone(verified_older_firmware_asset(replacement))


if __name__ == "__main__":
    unittest.main()
