import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quest_renamer.domain.build import BuildError
from quest_renamer.domain.models import BuildRequest, BundleDraft
from quest_renamer.domain.signers import SignerIdentity
from quest_renamer.infrastructure.apk_build_engine import (
    StagedApkBuildEngine,
    activate_source_replacement,
)
from quest_renamer.infrastructure.older_firmware_patch import PATCH_ID
from quest_renamer.infrastructure.process_runner import CommandResult
from quest_renamer.infrastructure.toolchain import Toolchain


class SimulatedToolRunner:
    def run(self, arguments: object, **kwargs: object) -> CommandResult:
        command = tuple(str(value) for value in arguments)  # type: ignore[union-attr]
        if "-genkeypair" in command:
            Path(command[command.index("-keystore") + 1]).write_bytes(b"keystore")
        elif "--onlyVerify" in command:
            pass
        elif "--apks" in command:
            output = Path(command[command.index("--out") + 1])
            output.mkdir(parents=True, exist_ok=True)
            (output / "game-aligned-signed.apk").write_bytes(b"signed apk")
        elif "d" in command:
            decoded = Path(command[command.index("-o") + 1])
            (decoded / "smali").mkdir(parents=True)
            (decoded / "AndroidManifest.xml").write_text(
                'package="com.example.game"', encoding="utf-8"
            )
            (decoded / "smali" / "Main.smali").write_text(
                "Lcom/example/game/Main;", encoding="utf-8"
            )
        elif "b" in command:
            Path(command[command.index("-o") + 1]).write_bytes(b"unsigned apk")
        return CommandResult(command, 0, ())


class RecordingToolRunner(SimulatedToolRunner):
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def run(self, arguments: object, **kwargs: object) -> CommandResult:
        command = tuple(str(value) for value in arguments)  # type: ignore[union-attr]
        self.commands.append(command)
        return super().run(arguments, **kwargs)


class BuildEngineTests(unittest.TestCase):
    def _engine(self, root: Path, **kwargs: object) -> StagedApkBuildEngine:
        java = root / "java"
        keytool = root / "keytool"
        apktool = root / "apktool.jar"
        signer = root / "signer.jar"
        for path in (java, keytool, apktool, signer):
            path.touch()
        return StagedApkBuildEngine(
            Toolchain(java, keytool, apktool, signer),
            signing_root=root / "data" / "signing",
            cache_root=root / "cache",
            runner=SimulatedToolRunner(),  # type: ignore[arg-type]
            **kwargs,  # type: ignore[arg-type]
        )

    def test_pipeline_publishes_complete_separate_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            apk = source / "game.apk"
            original_apk = b"original apk"
            apk.write_bytes(original_apk)
            obb = source / "main.42.com.example.game.obb"
            obb.write_bytes(b"obb data")
            java = root / "java"
            keytool = root / "keytool"
            apktool = root / "apktool.jar"
            signer = root / "signer.jar"
            for path in (java, keytool, apktool, signer):
                path.touch()
            output = root / "finished"
            request = BuildRequest(
                BundleDraft(
                    source,
                    apk,
                    (obb,),
                    game_name="Example",
                    package_name="com.example.game",
                    version_code="42",
                ),
                "com.dev.example.game",
                output,
            )
            engine = StagedApkBuildEngine(
                Toolchain(java, keytool, apktool, signer),
                signing_root=root / "data" / "signing",
                cache_root=root / "cache",
                runner=SimulatedToolRunner(),  # type: ignore[arg-type]
                recovery_record=root / "data" / "build-recovery.json",
            )

            progress_updates: list[tuple[float, str]] = []
            result = engine.build(
                request,
                progress=lambda value, message: progress_updates.append((value, message)),
            )

            self.assertEqual(apk.read_bytes(), original_apk)
            self.assertEqual(result.output_root, output.resolve())
            self.assertEqual(result.apk.read_bytes(), b"signed apk")
            self.assertTrue(result.manifest.is_file())
            self.assertTrue(result.report.is_file())
            self.assertEqual(len(result.obbs), 1)
            self.assertEqual(
                result.obbs[0].name,
                "main.42.com.dev.example.game.obb",
            )
            self.assertFalse(any(root.glob(".finished.staging-*")))
            self.assertFalse((root / "data" / "build-recovery.json").exists())
            self.assertTrue(any("Saving APK •" in message for _, message in progress_updates))
            self.assertTrue(
                any("Copying OBB 1 of 1 •" in message for _, message in progress_updates)
            )

    def test_patch_only_pipeline_keeps_package_identity_and_applies_patch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            apk = source / "game.apk"
            apk.write_bytes(b"original apk")
            asset = root / "libovrplatformloader.so"
            asset.write_bytes(b"verified fixture")
            request = BuildRequest(
                BundleDraft(source, apk, package_name="com.example.game"),
                "com.example.game",
                root / "finished",
                patches=(PATCH_ID,),
            )
            engine = self._engine(root, older_firmware_asset=asset)

            progress_updates: list[tuple[float, str]] = []
            with patch(
                "quest_renamer.infrastructure.apk_build_engine.apply_older_firmware_patch"
            ) as apply_patch:
                result = engine.build(
                    request,
                    progress=lambda value, message: progress_updates.append((value, message)),
                )

            apply_patch.assert_called_once()
            self.assertEqual(result.rewrite.changed_occurrences, 0)
            self.assertEqual(result.rewrite.changed_files, 0)
            self.assertEqual(result.apk.name, "com.example.game.apk")
            self.assertIn(
                (0.34, "Applying older-firmware compatibility patch"),
                progress_updates,
            )

    def test_same_package_identity_is_rejected_without_a_patch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            apk = source / "game.apk"
            apk.write_bytes(b"original apk")
            request = BuildRequest(
                BundleDraft(source, apk, package_name="com.example.game"),
                "com.example.game",
                root / "finished",
            )

            with self.assertRaisesRegex(BuildError, "patch-only"):
                self._engine(root).build(request)

    def test_obb_collision_is_rejected_before_staging_begins(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            first_root = source / "first"
            second_root = source / "second"
            first_root.mkdir()
            second_root.mkdir()
            apk = source / "game.apk"
            apk.write_bytes(b"original apk")
            first = first_root / "main.42.com.example.game.obb"
            second = second_root / "main.42.com.example.game.obb"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            request = BuildRequest(
                BundleDraft(
                    source,
                    apk,
                    (first, second),
                    package_name="com.example.game",
                    version_code="42",
                ),
                "com.dev.example.game",
                root / "finished",
            )

            with self.assertRaisesRegex(BuildError, "overwrite the same output"):
                self._engine(root).build(request)

            self.assertFalse(any(root.glob(".finished.staging-*")))

    def test_pipeline_replaces_source_only_after_build_and_trashes_original(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            apk = source / "game.apk"
            apk.write_bytes(b"original apk")
            obb = source / "main.42.com.example.game.obb"
            obb.write_bytes(b"original obb")
            trashed: list[bytes] = []

            def fake_trash(path: Path) -> None:
                trashed.append((path / "game.apk").read_bytes())
                shutil.rmtree(path)

            request = BuildRequest(
                BundleDraft(
                    source,
                    apk,
                    (obb,),
                    package_name="com.example.game",
                    version_code="42",
                ),
                "com.dev.example.game",
                source,
                replace_source=True,
            )
            engine = self._engine(root, move_to_trash=fake_trash)

            result = engine.build(request)

            self.assertEqual(result.output_root, source.resolve())
            self.assertEqual(result.apk.read_bytes(), b"signed apk")
            self.assertEqual(trashed, [b"original apk"])
            self.assertIsNone(result.recovery_root)
            self.assertFalse((source / "game.apk").exists())
            self.assertTrue((source / "quest-renamer-report.json").is_file())
            self.assertTrue((source / "quest-renamer-report.txt").is_file())
            self.assertTrue((source / "RENAME-REPORT.json").is_file())
            self.assertTrue((source / "RENAME-REPORT.txt").is_file())
            self.assertTrue((source / "RENAMED-BUNDLE.txt").is_file())
            readable_report = (source / "RENAME-REPORT.txt").read_text(encoding="utf-8")
            self.assertIn("BUILD AND CHANGE REPORT", readable_report)
            self.assertIn("com.example.game", readable_report)
            self.assertIn("com.dev.example.game", readable_report)
            machine_report = json.loads(
                (source / "quest-renamer-report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(machine_report["report_version"], 2)
            self.assertTrue(machine_report["apk"]["signature_verified"])
            self.assertEqual(result.report, source.resolve() / "RENAME-REPORT.json")
            self.assertEqual(result.text_report, source.resolve() / "RENAME-REPORT.txt")

    def test_recognized_source_signer_is_embedded_in_the_new_signing_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            apk = source / "game.apk"
            apk.write_bytes(b"original apk")
            runner = RecordingToolRunner()
            java = root / "java"
            keytool = root / "keytool"
            apktool = root / "apktool.jar"
            signer = root / "signer.jar"
            for path in (java, keytool, apktool, signer):
                path.touch()
            request = BuildRequest(
                BundleDraft(
                    source,
                    apk,
                    package_name="com.example.game",
                    signer_identity=SignerIdentity("nif", "NIF", "NothingIsFree"),
                ),
                "com.mr.example.game",
                root / "finished",
            )
            engine = StagedApkBuildEngine(
                Toolchain(java, keytool, apktool, signer),
                signing_root=root / "data" / "signing",
                cache_root=root / "cache",
                runner=runner,  # type: ignore[arg-type]
            )

            engine.build(request)

            key_commands = [command for command in runner.commands if "-genkeypair" in command]
            self.assertEqual(len(key_commands), 2)
            lineage_command = key_commands[-1]
            dname = lineage_command[lineage_command.index("-dname") + 1]
            self.assertIn("OU=mr", dname)
            self.assertIn("L=Previously signed by NothingIsFree (NIF)", dname)
            self.assertIn(
                "lineage-keys",
                lineage_command[lineage_command.index("-keystore") + 1],
            )

    def test_replacement_activation_rolls_back_if_the_swap_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            staging = root / ".source.staging-test"
            source.mkdir()
            staging.mkdir()
            (source / "original.apk").write_bytes(b"original")
            (staging / "renamed.apk").write_bytes(b"renamed")
            real_replace = os.replace
            calls = 0

            def fail_activation(old: Path, new: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated activation failure")
                real_replace(old, new)

            with (
                patch(
                    "quest_renamer.infrastructure.apk_build_engine.os.replace",
                    side_effect=fail_activation,
                ),
                self.assertRaises(BuildError),
            ):
                activate_source_replacement(source, staging)

            self.assertEqual((source / "original.apk").read_bytes(), b"original")
            self.assertEqual((staging / "renamed.apk").read_bytes(), b"renamed")


if __name__ == "__main__":
    unittest.main()
