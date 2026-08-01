import tempfile
import unittest
import zipfile
from pathlib import Path

from quest_renamer.domain.operations import CancellationToken, OperationCancelled
from quest_renamer.infrastructure.apk_analyzer import (
    ApktoolAnalyzer,
    hash_apk,
    inspect_apk_archive,
    parse_decoded_manifest,
)
from quest_renamer.infrastructure.process_runner import CommandResult
from quest_renamer.infrastructure.toolchain import Toolchain

MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.example.game" android:versionCode="42" android:versionName="1.2">
    <uses-sdk android:minSdkVersion="29" android:targetSdkVersion="32" />
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-feature android:name="android.hardware.vr.headtracking" />
    <application android:label="Example Game" android:debuggable="true" />
</manifest>
"""


class ManifestWritingRunner:
    def run(self, arguments: object, **kwargs: object) -> CommandResult:
        command = tuple(str(value) for value in arguments)  # type: ignore[union-attr]
        output_index = command.index("-o") + 1
        destination = Path(command[output_index])
        destination.mkdir(parents=True)
        (destination / "AndroidManifest.xml").write_text(MANIFEST, encoding="utf-8")
        return CommandResult(command, 0, ())


class SignatureAndManifestRunner(ManifestWritingRunner):
    def run(self, arguments: object, **kwargs: object) -> CommandResult:
        command = tuple(str(value) for value in arguments)  # type: ignore[union-attr]
        if "--onlyVerify" in command:
            output = (
                "Signer #1 certificate DN: CN=Quest APK Renamer, O=QAR, "
                "L=Previously signed by Example Studio (EXAMPLE)",
                "Signer #1 certificate issuer: CN=Quest APK Renamer, O=QAR",
                "Verified using v2 scheme (APK Signature Scheme v2): true",
            )
            return CommandResult(command, 0, output)
        return super().run(arguments, **kwargs)


class ApkAnalyzerTests(unittest.TestCase):
    def test_manifest_parser_returns_typed_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "AndroidManifest.xml"
            manifest.write_text(MANIFEST, encoding="utf-8")

            result = parse_decoded_manifest(manifest)

            self.assertEqual(result.package_name, "com.example.game")
            self.assertEqual(result.version_code, "42")
            self.assertEqual(result.permissions, ("android.permission.INTERNET",))
            self.assertTrue(result.debuggable)

    def test_archive_inspection_finds_abis_dex_and_native_libraries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            apk = Path(temporary) / "game.apk"
            with zipfile.ZipFile(apk, "w") as archive:
                archive.writestr("classes.dex", b"")
                archive.writestr("classes2.dex", b"")
                archive.writestr("lib/arm64-v8a/libgame.so", b"")
                archive.writestr("lib/arm64-v8a/libovrplatformloader.so", b"")
                archive.writestr("lib/armeabi-v7a/libgame.so", b"")

            result = inspect_apk_archive(apk)

            self.assertEqual(result.dex_files, 2)
            self.assertEqual(result.native_libraries, 3)
            self.assertEqual(result.abis, ("arm64-v8a", "armeabi-v7a"))
            self.assertTrue(result.has_legacy_loader)

    def test_analyzer_combines_manifest_archive_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            apk = root / "game.apk"
            with zipfile.ZipFile(apk, "w") as archive:
                archive.writestr("classes.dex", b"dex")
                archive.writestr("lib/arm64-v8a/libgame.so", b"native")
            java = root / "java"
            apktool = root / "apktool.jar"
            java.touch()
            apktool.touch()
            analyzer = ApktoolAnalyzer(
                Toolchain(java, None, apktool, None),
                runner=ManifestWritingRunner(),  # type: ignore[arg-type]
                temporary_root=root,
            )

            result = analyzer.analyze(apk)

            self.assertEqual(result.package_name, "com.example.game")
            self.assertEqual(result.abis, ("arm64-v8a",))
            self.assertEqual(result.dex_files, 1)
            self.assertEqual(len(result.sha256), 64)

    def test_analyzer_reports_the_embedded_signer_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            apk = root / "game.apk"
            with zipfile.ZipFile(apk, "w") as archive:
                archive.writestr("classes.dex", b"dex")
            java = root / "java"
            apktool = root / "apktool.jar"
            signer = root / "signer.jar"
            for tool in (java, apktool, signer):
                tool.touch()
            analyzer = ApktoolAnalyzer(
                Toolchain(java, None, apktool, signer),
                runner=SignatureAndManifestRunner(),  # type: ignore[arg-type]
                temporary_root=root,
            )

            result = analyzer.analyze(apk)

            self.assertEqual(
                result.signer_lineage,
                "Previously signed by Example Studio (EXAMPLE)",
            )
            self.assertIsNotNone(result.signer_identity)

    def test_hash_honors_a_pre_cancelled_operation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            apk = Path(temporary) / "game.apk"
            apk.write_bytes(b"apk")
            token = CancellationToken()
            token.cancel()

            with self.assertRaises(OperationCancelled):
                hash_apk(apk, token)


if __name__ == "__main__":
    unittest.main()
