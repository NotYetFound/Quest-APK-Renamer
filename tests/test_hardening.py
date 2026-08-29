"""Regression tests for correctness and performance fixes across the engines."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from quest_renamer.domain.operations import CancellationToken
from quest_renamer.infrastructure.activity_log import ActivityLog
from quest_renamer.infrastructure.adb_device import AdbDeviceService
from quest_renamer.infrastructure.adb_installer import classify_install_failure
from quest_renamer.infrastructure.apk_analyzer import ApktoolAnalyzer, parse_apktool_metadata
from quest_renamer.infrastructure.local_bundles import LocalBundleInspector
from quest_renamer.infrastructure.package_rewriter import replace_package_references
from quest_renamer.infrastructure.process_runner import (
    CommandResult,
    ProcessRunner,
    describe_command_failure,
)
from quest_renamer.infrastructure.reference_scanner import (
    PackagePatterns,
    count_file_patterns,
    is_technical_file,
)
from quest_renamer.infrastructure.signing_backup import SigningIdentityManager
from quest_renamer.infrastructure.signing_identity import signing_identity_is_incomplete
from quest_renamer.infrastructure.toolchain import Toolchain


class ReferenceBoundaryTests(unittest.TestCase):
    def test_prefix_and_parent_packages_are_not_references(self) -> None:
        patterns = PackagePatterns.for_package("com.example.game")
        self.assertEqual(patterns.count(b'package="com.example.game"'), (1, 0))
        self.assertEqual(patterns.count(b"com.example.game.provider"), (1, 0))
        self.assertEqual(patterns.count(b"com.example.gamepad.Provider"), (0, 0))
        self.assertEqual(patterns.count(b"org.foo.com.example.game"), (0, 0))
        self.assertEqual(patterns.count(b"com.example.game2"), (0, 0))
        self.assertEqual(patterns.count(b"Lcom/example/game/Main;"), (0, 1))
        self.assertEqual(patterns.count(b"[Lcom/example/game/Main;"), (0, 1))
        self.assertEqual(patterns.count(b"Lcom/example/gamepad/Main;"), (0, 0))
        self.assertEqual(patterns.count(b"Lorg/foo/com/example/game/Main;"), (0, 0))

    def test_substitution_rewrites_sub_packages_but_not_neighbours(self) -> None:
        patterns = PackagePatterns.for_package("com.example.game")
        updated, count = patterns.substitute(
            b'Lcom/example/game/ui/A; "com.example.game" com.example.gamepad',
            "com.example.game.mr",
        )
        self.assertEqual(count, 1)
        self.assertEqual(
            updated, b'Lcom/example/game/ui/A; "com.example.game.mr" com.example.gamepad'
        )
        self.assertEqual(
            patterns.substitute(b"com.example.game.sub com.example.game.ui.Main", "x.y")[0],
            b"x.y.sub com.example.game.ui.Main",
        )

    def test_chunked_counting_matches_whole_file_counting(self) -> None:
        patterns = PackagePatterns.for_package("com.example.game")
        body = (
            b"xx com.example.game yy Lcom/example/game/X; zz com.example.gamepad "
            b"com.example.game.sub\n"
        ) * 40
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "blob.bin"
            path.write_bytes(body)
            whole = patterns.count(body)
            for chunk_size in (5, 13, 64, 1000):
                counted = count_file_patterns(
                    path,
                    patterns,
                    CancellationToken(),
                    max_size=1 << 20,
                    chunk_size=chunk_size,
                )
                self.assertEqual(counted, whole, f"chunk size {chunk_size}")

    def test_technical_file_predicate(self) -> None:
        self.assertTrue(is_technical_file("AndroidManifest.xml"))
        self.assertTrue(is_technical_file("smali_classes2/com/a/B.smali"))
        self.assertTrue(is_technical_file("res/xml/paths.xml"))
        self.assertFalse(is_technical_file("assets/config.xml"))
        self.assertFalse(is_technical_file("lib/arm64-v8a/libgame.so"))

    def test_rewriter_leaves_prefix_packages_alone(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            decoded = Path(temporary)
            smali = decoded / "smali" / "Main.smali"
            smali.parent.mkdir(parents=True)
            smali.write_text(
                "Lcom/example/game/Main;\nLcom/example/gamepad/Pad;\n"
                'const-string v0, "com.example.game.provider"\n'
                'const-string v1, "com.example.gamepad"\n',
                encoding="utf-8",
            )
            (decoded / "AndroidManifest.xml").write_text(
                'package="com.example.game" authorities="com.example.gamepad.files"',
                encoding="utf-8",
            )

            result = replace_package_references(
                decoded, "com.example.game", "com.example.game.mr", token=CancellationToken()
            )

            self.assertEqual(result.changed_files, 2)
            self.assertEqual(result.changed_occurrences, 2)
            self.assertEqual(result.namespace_references, 1)
            text = smali.read_text(encoding="utf-8")
            self.assertIn("Lcom/example/game/Main;", text)
            self.assertIn("Lcom/example/gamepad/Pad;", text)
            self.assertIn("com.example.game.mr.provider", text)
            self.assertIn('"com.example.gamepad"', text)
            manifest = (decoded / "AndroidManifest.xml").read_text(encoding="utf-8")
            self.assertIn('package="com.example.game.mr"', manifest)
            self.assertIn("com.example.gamepad.files", manifest)

    def test_rewriter_rejects_an_empty_source_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, self.assertRaises(ValueError):
            replace_package_references(
                Path(temporary), "", "com.example.game", token=CancellationToken()
            )


STRIPPED_MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.example.game">
    <application android:label="Example Game" />
</manifest>
"""

APKTOOL_YML = """!!brut.androlib.apk.ApkInfo
apkFileName: game.apk
sdkInfo:
  minSdkVersion: '29'
  targetSdkVersion: '32'
versionInfo:
  versionCode: '42'
  versionName: 1.2.3
"""


class StrippedManifestRunner:
    def run(self, arguments: object, **kwargs: object) -> CommandResult:
        command = tuple(str(value) for value in arguments)  # type: ignore[union-attr]
        output_index = command.index("-o") + 1
        destination = Path(command[output_index])
        destination.mkdir(parents=True)
        (destination / "AndroidManifest.xml").write_text(STRIPPED_MANIFEST, encoding="utf-8")
        (destination / "apktool.yml").write_text(APKTOOL_YML, encoding="utf-8")
        return CommandResult(command, 0, ())


class AnalyzerFallbackTests(unittest.TestCase):
    def test_version_and_sdk_fall_back_to_apktool_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            java = root / "java"
            apktool = root / "apktool.jar"
            java.touch()
            apktool.touch()
            apk = root / "game.apk"
            import zipfile

            with zipfile.ZipFile(apk, "w") as archive:
                archive.writestr("classes.dex", b"")
            analyzer = ApktoolAnalyzer(
                Toolchain(java, None, apktool, None),
                runner=StrippedManifestRunner(),  # type: ignore[arg-type]
                temporary_root=root,
            )

            result = analyzer.analyze(apk)

            self.assertEqual(result.package_name, "com.example.game")
            self.assertEqual(result.version_code, "42")
            self.assertEqual(result.version_name, "1.2.3")
            self.assertEqual(result.min_sdk, "29")
            self.assertEqual(result.target_sdk, "32")

    def test_metadata_parser_tolerates_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "apktool.yml"
            path.write_text(APKTOOL_YML, encoding="utf-8")
            self.assertEqual(parse_apktool_metadata(path)["version_code"], "42")
            self.assertEqual(parse_apktool_metadata(path)["version_name"], "1.2.3")


class SigningRootTests(unittest.TestCase):
    def test_app_created_folders_do_not_make_the_identity_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "signing"
            (root / "app-icons").mkdir(parents=True)
            (root / "imported-identities").mkdir()
            self.assertFalse(signing_identity_is_incomplete(root))
            state = SigningIdentityManager(root).state()
            self.assertFalse(state.exists)
            self.assertIn("Created automatically", state.detail)

    def test_half_an_identity_or_a_migration_marker_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "signing"
            root.mkdir()
            (root / "identity.json").write_text("{}", encoding="utf-8")
            self.assertTrue(signing_identity_is_incomplete(root))
            (root / "identity.json").unlink()
            (root / "legacy-migration-error.txt").write_text("boom", encoding="utf-8")
            self.assertTrue(signing_identity_is_incomplete(root))


class ProcessRunnerTests(unittest.TestCase):
    def test_failure_description_skips_java_stack_frames(self) -> None:
        output = (
            "I: Using Apktool 3.0.3",
            "Exception in thread \"main\" brut.androlib.exceptions.AndrolibException: "
            "Could not decode arsc file",
            "\tat brut.androlib.res.decoder.ARSCDecoder.decode(ARSCDecoder.java:70)",
            "\tat brut.apktool.Main.main(Main.java:76)",
            "\t... 13 more",
        )
        detail = describe_command_failure(output)
        self.assertIn("Could not decode arsc file", detail)
        self.assertNotIn("13 more", detail)
        self.assertEqual(describe_command_failure(()), "No diagnostic output was produced.")

    def test_commands_never_wait_on_an_inherited_stdin(self) -> None:
        runner = ProcessRunner(default_timeout=20)
        result = runner.run(
            (
                sys.executable,
                "-c",
                "import sys; data = sys.stdin.read(); print('read', len(data))",
            ),
            timeout=20,
        )
        self.assertEqual(result.output, ("read 0",))


class InstallFailureClassificationTests(unittest.TestCase):
    def test_known_codes_get_friendly_text(self) -> None:
        text = classify_install_failure(
            ("Performing Streamed Install", "Failure [INSTALL_FAILED_VERSION_DOWNGRADE]")
        )
        self.assertIn("newer version", text)
        self.assertIn("INSTALL_FAILED_VERSION_DOWNGRADE", text)

    def test_unknown_codes_are_reported_verbatim(self) -> None:
        text = classify_install_failure(("Failure [INSTALL_FAILED_SOMETHING_NEW: detail]",))
        self.assertIn("INSTALL_FAILED_SOMETHING_NEW", text)
        self.assertIn("detail", text)
        self.assertEqual(classify_install_failure(("Success",)), "")


class LocalBundleCaseTests(unittest.TestCase):
    def test_upper_case_apk_and_obb_extensions_are_recognised(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "Game"
            obb_dir = folder / "com.example.game"
            obb_dir.mkdir(parents=True)
            (folder / "Game.APK").write_bytes(b"apk")
            (obb_dir / "main.42.com.example.game.OBB").write_bytes(b"obb")
            (folder / "release.manifest").write_text(
                "Game Name;Release Name;Package Name;Version Code\n"
                "Game;Game;com.example.game;42\n",
                encoding="utf-8",
            )

            bundle = LocalBundleInspector().inspect_folder(folder)

            self.assertEqual(bundle.apk.name, "Game.APK")
            self.assertEqual(len(bundle.obbs), 1)


class ActivityLogTailTests(unittest.TestCase):
    def test_tail_returns_the_last_lines_of_a_large_log(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "app.log"
            lines = [f"line {index} " + "x" * 200 for index in range(3000)]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            log = ActivityLog(path, max_view_lines=400)

            tail = log.tail()

            self.assertEqual(len(tail), 400)
            self.assertEqual(tail[0], lines[-400])
            self.assertEqual(tail[-1], lines[-1])

    def test_tail_of_a_short_log_returns_everything(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "app.log"
            path.write_text("one\ntwo\n", encoding="utf-8")
            self.assertEqual(ActivityLog(path).tail(), ("one", "two"))


class DevicePreferenceTests(unittest.TestCase):
    def test_a_single_quest_is_selected_next_to_a_phone(self) -> None:
        calls: list[list[str]] = []

        def fake_run(
            arguments: list[str], **_kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            calls.append(list(arguments))
            if arguments[1:3] == ["devices", "-l"]:
                return subprocess.CompletedProcess(
                    arguments,
                    0,
                    "List of devices attached\n"
                    "PHONE1 device product:sdk_phone model:Pixel_7 device:panther_phone\n"
                    "QUEST1 device product:eureka model:Quest_3 device:eureka\n",
                    "",
                )
            if "getprop" in arguments:
                return subprocess.CompletedProcess(arguments, 0, "Quest 3\n", "")
            if "df" in arguments:
                return subprocess.CompletedProcess(
                    arguments, 0, "Filesystem 1K-blocks Used Available Use% Mounted\n"
                    "/dev/fuse 100 50 50 50% /sdcard\n", ""
                )
            return subprocess.CompletedProcess(arguments, 0, "", "")

        service = AdbDeviceService(adb=Path("/usr/bin/adb"), run=fake_run)  # type: ignore[arg-type]
        snapshot = service.snapshot()

        self.assertTrue(snapshot.connected)
        self.assertEqual(snapshot.serial, "QUEST1")

    def test_two_quests_still_require_a_choice(self) -> None:
        def fake_run(
            arguments: list[str], **_kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                arguments,
                0,
                "List of devices attached\n"
                "QUEST1 device product:eureka model:Quest_3 device:eureka\n"
                "QUEST2 device product:hollywood model:Quest_2 device:hollywood\n",
                "",
            )

        service = AdbDeviceService(adb=Path("/usr/bin/adb"), run=fake_run)  # type: ignore[arg-type]
        self.assertEqual(service.snapshot().status, "multiple")


if __name__ == "__main__":
    unittest.main()


class WirelessAndPickerTests(unittest.TestCase):
    def test_several_devices_expose_candidates_and_honour_the_preferred_serial(self) -> None:
        listing = (
            "List of devices attached\n"
            "QUEST1 device product:eureka model:Quest_3 device:eureka\n"
            "QUEST2 device product:hollywood model:Quest_2 device:hollywood\n"
        )

        def fake_run(
            arguments: list[str], **_kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            if arguments[1:3] == ["devices", "-l"]:
                return subprocess.CompletedProcess(arguments, 0, listing, "")
            if "getprop" in arguments:
                return subprocess.CompletedProcess(arguments, 0, "Quest\n", "")
            return subprocess.CompletedProcess(arguments, 0, "", "")

        service = AdbDeviceService(adb=Path("/usr/bin/adb"), run=fake_run)  # type: ignore[arg-type]
        snapshot = service.snapshot()
        self.assertEqual(snapshot.status, "multiple")
        serials = [serial for serial, _label in snapshot.candidates]
        self.assertEqual(serials, ["QUEST1", "QUEST2"])
        self.assertIn("Quest 2", snapshot.candidates[1][1])

        service.set_preferred_serial("QUEST2")
        chosen = service.snapshot()
        self.assertTrue(chosen.connected)
        self.assertEqual(chosen.serial, "QUEST2")

    def test_wireless_connect_parses_adb_replies(self) -> None:
        from quest_renamer.infrastructure.adb_device import (
            normalize_wireless_address,
            parse_route_source,
            parse_wlan_address,
        )

        self.assertEqual(normalize_wireless_address("192.168.1.20"), "192.168.1.20:5555")
        self.assertEqual(
            normalize_wireless_address("adb connect 192.168.1.20:4242"), "192.168.1.20:4242"
        )
        self.assertEqual(
            parse_wlan_address("inet 192.168.1.44/24 brd 192.168.1.255 scope global wlan0"),
            "192.168.1.44",
        )
        self.assertEqual(
            parse_route_source(
                "192.168.1.0/24 dev wlan0 proto kernel scope link src 192.168.1.44"
            ),
            "192.168.1.44",
        )
        replies = {"ok": "connected to 192.168.1.44:5555", "bad": "failed to connect to x"}

        def fake_run(
            arguments: list[str], **_kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            key = "ok" if arguments[-1].startswith("192.168.1.44") else "bad"
            return subprocess.CompletedProcess(arguments, 0, replies[key], "")

        service = AdbDeviceService(adb=Path("/usr/bin/adb"), run=fake_run)  # type: ignore[arg-type]
        self.assertIn("connected", service.connect_wireless("192.168.1.44"))
        with self.assertRaises(OSError):
            service.connect_wireless("10.0.0.9:5555")
