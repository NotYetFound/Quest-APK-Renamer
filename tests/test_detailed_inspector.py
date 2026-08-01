import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QUrl

from quest_renamer.domain.inspection import (
    CertificateDetail,
    DetailedApkAnalysis,
    ReferenceHit,
    ReferencePreview,
    SignatureDetail,
)
from quest_renamer.domain.signers import SignerIdentity
from quest_renamer.infrastructure.detailed_apk_inspector import (
    FullDecodeApkInspector,
    write_analysis_report,
)
from quest_renamer.infrastructure.process_runner import CommandResult
from quest_renamer.infrastructure.toolchain import Toolchain
from quest_renamer.presentation.inspector_controller import InspectorController

MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.example.game" android:versionCode="42" android:versionName="1.2"
    android:compileSdkVersion="35">
    <uses-sdk android:minSdkVersion="29" android:targetSdkVersion="32" />
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-feature android:name="android.hardware.vr.headtracking" android:required="true" />
    <uses-feature android:glEsVersion="0x00030001" />
    <application android:label="@string/app_name" android:debuggable="true"
        android:extractNativeLibs="false">
        <activity android:name=".MainActivity" />
        <service android:name=".GameService" />
    </application>
</manifest>
"""


class DetailedRunner:
    def run(self, arguments: object, **_kwargs: object) -> CommandResult:
        command = tuple(str(value) for value in arguments)  # type: ignore[union-attr]
        if "--onlyVerify" in command:
            output = (
                "Verified using v2 scheme (APK Signature Scheme v2): true",
                "Signer #1 certificate DN: CN=NothingIsFree, O=NIF",
                "Signer #1 certificate issuer: CN=NothingIsFree, O=NIF",
                "Signer #1 certificate SHA-256 digest: " + "a" * 64,
                "Signer #1 certificate SHA-1 digest: " + "b" * 40,
            )
            return CommandResult(command, 0, output)
        decoded = Path(command[command.index("-o") + 1])
        (decoded / "res" / "values").mkdir(parents=True)
        (decoded / "smali").mkdir()
        (decoded / "assets").mkdir()
        (decoded / "lib" / "arm64-v8a").mkdir(parents=True)
        (decoded / "AndroidManifest.xml").write_text(MANIFEST, encoding="utf-8")
        (decoded / "apktool.yml").write_text("versionCode: '42'\n", encoding="utf-8")
        (decoded / "res" / "values" / "strings.xml").write_text(
            '<resources><string name="app_name">Example Game</string></resources>',
            encoding="utf-8",
        )
        (decoded / "smali" / "Main.smali").write_text(
            "Lcom/example/game/Main;", encoding="utf-8"
        )
        (decoded / "assets" / "note.txt").write_text("com.example.game", encoding="utf-8")
        (decoded / "lib" / "arm64-v8a" / "libgame.so").write_bytes(b"com.example.game")
        return CommandResult(command, 0, ())


class ImmediateInspector:
    def inspect(self, apk: Path, **kwargs: object) -> DetailedApkAnalysis:
        progress = kwargs.get("progress")
        if callable(progress):
            progress(1.0, "Inspection complete")
        return DetailedApkAnalysis(
            apk.resolve(),
            "com.example.game",
            apk.stat().st_size,
            app_label="Example Game",
            target_sdk="32",
            permissions=("android.permission.INTERNET",),
            abis=("arm64-v8a",),
            signature=SignatureDetail(
                True,
                True,
                ("v2",),
                (CertificateDetail("CN=NothingIsFree", "CN=NothingIsFree"),),
                SignerIdentity("nif", "NIF", "NothingIsFree"),
                lineage="Previously signed by Automagic Package Changer (APC)",
            ),
            references=ReferencePreview(
                "com.example.game",
                1,
                (ReferenceHit("AndroidManifest.xml", 1, 1, 0),),
            ),
        )


class DetailedInspectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QCoreApplication.instance() or QCoreApplication([])

    def test_full_inspection_matches_original_metadata_and_rename_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            apk = root / "game.apk"
            with zipfile.ZipFile(apk, "w") as archive:
                archive.writestr("classes.dex", b"dex")
                archive.writestr("lib/arm64-v8a/libgame.so", b"native")
                archive.writestr("res/values-fr/strings.xml", b"resources")
            original = apk.read_bytes()
            java = root / "java"
            apktool = root / "apktool.jar"
            signer = root / "signer.jar"
            for path in (java, apktool, signer):
                path.touch()
            registry = (
                Path(__file__).parents[1]
                / "src"
                / "quest_renamer"
                / "resources"
                / "known-signers.json"
            )
            inspector = FullDecodeApkInspector(
                Toolchain(java, None, apktool, signer),
                signer_registry=registry,
                runner=DetailedRunner(),  # type: ignore[arg-type]
                temporary_root=root / "cache",
            )

            result = inspector.inspect(apk)

            self.assertEqual(apk.read_bytes(), original)
            self.assertEqual(result.package_name, "com.example.game")
            self.assertEqual(result.app_label, "Example Game")
            self.assertEqual(result.gl_es_version, "3.1")
            self.assertEqual(result.abis, ("arm64-v8a",))
            self.assertEqual(result.locales, ("fr",))
            self.assertEqual(result.signature.identity.id, "nif")  # type: ignore[union-attr]
            self.assertEqual(result.signature.schemes, ("v2",))
            self.assertEqual(result.references.technical_occurrences, 2)
            self.assertEqual(len(result.references.preserved_files), 2)
            self.assertEqual(len(result.references.native_warnings), 1)
            self.assertEqual(
                {name for name, _digest in result.hashes}, {"md5", "sha1", "sha256"}
            )

    def test_json_export_is_complete_and_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            apk = root / "game.apk"
            apk.write_bytes(b"apk")
            analysis = ImmediateInspector().inspect(apk)
            destination = root / "analysis.json"

            write_analysis_report(destination, analysis)
            payload = json.loads(destination.read_text(encoding="utf-8"))

            self.assertEqual(payload["package_name"], "com.example.game")
            self.assertEqual(payload["signature"]["identity"]["id"], "nif")
            self.assertEqual(
                payload["signature"]["lineage"],
                "Previously signed by Automagic Package Changer (APC)",
            )
            self.assertFalse((root / "analysis.json.tmp").exists())

    def test_controller_runs_inspection_and_exports_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            apk = root / "game.apk"
            apk.write_bytes(b"apk")
            controller = InspectorController(ImmediateInspector())

            controller.inspectPath(str(apk))
            self._wait_until(lambda: controller.hasAnalysis)
            destination = root / "report"
            controller.exportAnalysis(QUrl.fromLocalFile(str(destination)))

            self.assertEqual(controller.title, "Example Game")
            self.assertEqual(controller.signerLabel, "NIF")
            self.assertIn(
                {
                    "label": "Embedded signer lineage",
                    "value": "Previously signed by Automagic Package Changer (APC)",
                },
                controller.signingRows,
            )
            self.assertIn("1 technical references", controller.referenceSummary)
            self.assertTrue((root / "report.json").is_file())

    def _wait_until(self, condition: object) -> None:
        deadline = time.monotonic() + 2
        while not condition():  # type: ignore[operator]
            self.application.processEvents()
            if time.monotonic() >= deadline:
                self.fail("Timed out waiting for APK inspection.")
            time.sleep(0.005)


if __name__ == "__main__":
    unittest.main()
