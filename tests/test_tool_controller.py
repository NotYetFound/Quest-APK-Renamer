import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from quest_renamer.infrastructure.tool_manager import PinnedToolManager
from quest_renamer.presentation.tool_controller import ToolController


class ToolControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QCoreApplication.instance() or QCoreApplication([])

    def test_verified_tools_activate_without_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            resources = root / "resources"
            managed = root / "data" / "tools"
            resources.mkdir()
            managed.mkdir(parents=True)
            payloads = {"apktool": b"apktool", "uber_apk_signer": b"signer"}
            catalog = {
                key: {
                    "file": f"{key}.jar",
                    "version": "1",
                    "url": f"https://example.invalid/{key}.jar",
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
                for key, payload in payloads.items()
            }
            catalog_path = resources / "toolchain.json"
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
            for key, payload in payloads.items():
                (managed / f"{key}.jar").write_bytes(payload)
            activations: list[bool] = []
            controller = ToolController(
                PinnedToolManager(
                    catalog_path=catalog_path,
                    resource_root=root,
                    data_root=root / "data",
                    environment={},
                ),
                activate_tools=lambda: activations.append(True),
            )

            controller.repair()
            deadline = time.monotonic() + 2
            while controller.isBusy and time.monotonic() < deadline:
                self.application.processEvents()
                time.sleep(0.005)
            self.application.processEvents()

            self.assertFalse(controller.isBusy)
            self.assertTrue(controller.allReady)
            self.assertEqual(activations, [True])
            self.assertEqual(controller.tone, "success")


if __name__ == "__main__":
    unittest.main()
