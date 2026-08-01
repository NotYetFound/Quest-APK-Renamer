import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from quest_renamer.infrastructure.toolchain import (
    load_tool_catalog,
    resolve_toolchain,
)


class ToolchainTests(unittest.TestCase):
    def _fixture(self, root: Path, *, damaged: bool = False) -> tuple[Path, Path, Path]:
        resources = root / "resources"
        tools = root / "tools"
        java_home = root / "java"
        resources.mkdir()
        tools.mkdir()
        (java_home / "bin").mkdir(parents=True)
        apktool_bytes = b"damaged" if damaged else b"apktool"
        signer_bytes = b"signer"
        (tools / "apktool.jar").write_bytes(apktool_bytes)
        (tools / "signer.jar").write_bytes(signer_bytes)
        java = java_home / "bin" / "java"
        keytool = java_home / "bin" / "keytool"
        java.touch()
        keytool.touch()
        catalog = {
            "apktool": {
                "file": "apktool.jar",
                "version": "1",
                "url": "https://example.invalid/apktool",
                "sha256": hashlib.sha256(b"apktool").hexdigest(),
            },
            "uber_apk_signer": {
                "file": "signer.jar",
                "version": "1",
                "url": "https://example.invalid/signer",
                "sha256": hashlib.sha256(signer_bytes).hexdigest(),
            },
        }
        (resources / "toolchain.json").write_text(json.dumps(catalog), encoding="utf-8")
        return tools, java, keytool

    def test_checked_in_catalog_has_complete_pins(self) -> None:
        root = Path(__file__).parents[1] / "src" / "quest_renamer"
        catalog = load_tool_catalog(root / "resources" / "toolchain.json")
        self.assertEqual(catalog["apktool"].version, "3.0.3")
        self.assertEqual(len(catalog["apktool"].sha256), 64)
        self.assertEqual(catalog["uber_apk_signer"].version, "1.3.0")
        self.assertEqual(
            catalog["older_firmware_patch"].sha256,
            "1f6d43e6b7b82960efdaf6596953272c32022316375ddca1eddc56e15b026ca2",
        )

    def test_resolver_accepts_verified_explicit_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tools, java, keytool = self._fixture(root)

            result = resolve_toolchain(
                resource_root=root,
                executable=root / "app",
                data_root=root / "data",
                environment={
                    "QAR_TOOLS_DIR": str(tools),
                    "QAR_JAVA": str(java),
                    "QAR_KEYTOOL": str(keytool),
                },
            )

            self.assertTrue(result.build_ready)
            self.assertEqual(result.problems, ())

    def test_resolver_rejects_a_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tools, java, keytool = self._fixture(root, damaged=True)

            result = resolve_toolchain(
                resource_root=root,
                executable=root / "app",
                data_root=root / "data",
                environment={
                    "QAR_TOOLS_DIR": str(tools),
                    "QAR_JAVA": str(java),
                    "QAR_KEYTOOL": str(keytool),
                },
            )

            self.assertFalse(result.analysis_ready)
            self.assertTrue(any("integrity" in problem for problem in result.problems))

    def test_resolver_skips_a_damaged_earlier_copy_for_a_valid_managed_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tools, java, keytool = self._fixture(root, damaged=True)
            managed = root / "data" / "tools"
            managed.mkdir(parents=True)
            (managed / "apktool.jar").write_bytes(b"apktool")
            (managed / "signer.jar").write_bytes(b"signer")

            result = resolve_toolchain(
                resource_root=root,
                executable=root / "app",
                data_root=root / "data",
                environment={
                    "QAR_TOOLS_DIR": str(tools),
                    "QAR_JAVA": str(java),
                    "QAR_KEYTOOL": str(keytool),
                },
            )

            self.assertTrue(result.build_ready)
            self.assertEqual(result.apktool, (managed / "apktool.jar").resolve())
            self.assertEqual(result.problems, ())


if __name__ == "__main__":
    unittest.main()
