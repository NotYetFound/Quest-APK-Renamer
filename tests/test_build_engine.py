import hashlib
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from expansion_fixtures import build_catalog, write_obb

from quest_renamer.domain.build import BuildError, BuildResult
from quest_renamer.domain.models import BuildRequest, BundleDraft
from quest_renamer.domain.signers import SignerIdentity
from quest_renamer.infrastructure.addressables_catalog import (
    CATALOG_ENTRY,
    resolve_catalog_internal_ids,
)
from quest_renamer.infrastructure.apk_build_engine import (
    StagedApkBuildEngine,
    activate_source_replacement,
)
from quest_renamer.infrastructure.older_firmware_patch import PATCH_ID
from quest_renamer.infrastructure.process_runner import CommandFailed, CommandResult
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
                '<manifest package="com.example.game">'
                '<application android:label="@string/app_name"/></manifest>',
                encoding="utf-8",
            )
            (decoded / "smali" / "Main.smali").write_text(
                "Lcom/example/game/Main;", encoding="utf-8"
            )
            (decoded / "res" / "values").mkdir(parents=True)
            (decoded / "res" / "values" / "strings.xml").write_text(
                '<resources><string name="app_name">Example Game</string></resources>',
                encoding="utf-8",
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


class ExpansionPathToolRunner(SimulatedToolRunner):
    def __init__(self, obb_name: str = "main.42.com.example.game.obb") -> None:
        self.obb_name = obb_name

    def run(self, arguments: object, **kwargs: object) -> CommandResult:
        command = tuple(str(value) for value in arguments)  # type: ignore[union-attr]
        result = super().run(arguments, **kwargs)
        if "d" in command:
            decoded = Path(command[command.index("-o") + 1])
            package = self.obb_name.split(".", 2)[2].removesuffix(".obb")
            (decoded / "AndroidManifest.xml").write_text(
                f'<manifest package="{package}">'
                '<application android:label="@string/app_name"/></manifest>',
                encoding="utf-8",
            )
            (decoded / "smali" / "Main.smali").write_text(
                f'L{package.replace(".", "/")}/Main;', encoding="utf-8"
            )
            config = decoded / "lib" / "arm64-v8a" / "libfrda.config.so"
            config.parent.mkdir(parents=True)
            config.write_text(
                f'{{"path":"{self.obb_name}","type":"default"}}',
                encoding="utf-8",
            )
        return result


class BuildEngineTests(unittest.TestCase):
    def test_ambiguous_signer_output_cannot_skip_verification_or_replace_output(self) -> None:
        class RejectingVerifier(SimulatedToolRunner):
            def run(self, arguments: object, **kwargs: object) -> CommandResult:
                result = super().run(arguments, **kwargs)
                if "--onlyVerify" in result.command:
                    raise CommandFailed(result.command, 1, ("Signature verification failed",))
                if "--apks" in result.command:
                    return CommandResult(
                        result.command, 0,
                        ("Signature verification failed: signature verified: false",),
                    )
                return result

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            apk = source / "game.apk"
            apk.write_bytes(b"apk")
            output = root / "output"
            output.mkdir()
            (output / "old.txt").write_bytes(b"old output")
            request = BuildRequest(
                BundleDraft(source, apk, package_name="com.example.game"),
                "com.dev.example.game", output, replace_output=True,
            )
            engine = self._engine(root)
            engine.runner = RejectingVerifier()  # type: ignore[assignment]
            with self.assertRaisesRegex(BuildError, "Signature verification failed"):
                engine.build(request)
            self.assertEqual(list(output.iterdir()), [output / "old.txt"])
            self.assertEqual((output / "old.txt").read_bytes(), b"old output")

    def test_source_replacement_rejects_exact_apk_and_unrelated_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            apk = source / "game.apk"
            apk.write_bytes(b"apk")
            (source / "notes.txt").write_bytes(b"notes")
            for exact, message in ((True, "individual APK"), (False, "notes.txt")):
                with self.subTest(exact=exact):
                    request = BuildRequest(
                        BundleDraft(
                            source, apk, package_name="com.example.game", selected_as_apk=exact,
                        ),
                        "com.dev.example.game", source, replace_source=True,
                    )
                    with self.assertRaisesRegex(BuildError, message):
                        self._engine(root).build(request)
            self.assertEqual(apk.read_bytes(), b"apk")
            self.assertEqual((source / "notes.txt").read_bytes(), b"notes")

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
                app_label_suffix="(Dev)",
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
            self.assertEqual(result.app_label, "Example Game (Dev)")
            self.assertEqual(result.rewrite.label_before, "Example Game")
            self.assertIn("Example Game (Dev)", result.text_report.read_text())  # type: ignore[union-attr]
            self.assertEqual(result.output_root, output.resolve())
            self.assertEqual(result.apk.read_bytes(), b"signed apk")
            self.assertTrue(result.manifest.is_file())
            self.assertTrue(result.report.is_file())
            report = json.loads(result.report.read_text(encoding="utf-8"))
            self.assertEqual(report["apk"]["sha256"], hashlib.sha256(b"signed apk").hexdigest())
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

    def test_non_obb_files_in_the_obb_folder_are_carried_to_the_renamed_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            data = source / "com.example.game"
            (data / "extra").mkdir(parents=True)
            apk = source / "game.apk"
            apk.write_bytes(b"original apk")
            obb = data / "main.42.com.example.game.obb"
            obb.write_bytes(b"obb data")
            (data / "settings.json").write_text("{}", encoding="utf-8")
            (data / "extra" / "pack.dat").write_bytes(b"pack")
            request = BuildRequest(
                BundleDraft(
                    source,
                    apk,
                    (obb,),
                    package_name="com.example.game",
                    version_code="42",
                ),
                "com.dev.example.game",
                root / "finished",
            )

            result = self._engine(root).build(request)

            renamed = result.output_root / "com.dev.example.game"
            self.assertEqual((renamed / "settings.json").read_text(), "{}")
            self.assertEqual((renamed / "extra" / "pack.dat").read_bytes(), b"pack")
            manifest = result.manifest.read_text(encoding="utf-8-sig")
            self.assertIn("d;./com.dev.example.game/extra;0", manifest)
            self.assertIn("f;./com.dev.example.game/extra/pack.dat;4", manifest)
            self.assertEqual(len(result.obbs), 1)
            report = json.loads(result.report.read_text(encoding="utf-8"))
            self.assertEqual(
                report["extra_files"],
                [
                    "com.dev.example.game/extra/pack.dat",
                    "com.dev.example.game/settings.json",
                ],
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

    def test_game_fixes_are_skipped_when_the_package_id_is_unchanged(self) -> None:
        class SpyFix:
            fix_id = "spy-fix"
            title = "Spy"
            source_packages = frozenset({"com.example.game"})

            def __init__(self) -> None:
                self.calls = 0

            def apply_to_decoded_apk(self, context: object, decoded: Path) -> object:
                self.calls += 1
                raise AssertionError("fix must not run for an unchanged package")

            def apply_to_obb(self, context: object, obb_path: Path) -> tuple[str, ...]:
                self.calls += 1
                raise AssertionError("fix must not run for an unchanged package")

        spy = SpyFix()
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
            with (
                patch(
                    "quest_renamer.infrastructure.apk_build_engine.fixes_for",
                    return_value=(spy,),
                ),
                patch(
                    "quest_renamer.infrastructure.apk_build_engine.apply_older_firmware_patch"
                ),
            ):
                result = engine.build(request)

            self.assertEqual(spy.calls, 0)
            self.assertEqual(result.rewrite.game_fixes, ())

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

    def _expansion_build(
        self,
        root: Path,
        source_package: str,
        target_package: str,
        obb_payload: bytes,
        logs: list[str] | None = None,
    ) -> tuple[BuildResult, Path]:
        source = root / "source"
        source.mkdir()
        apk = source / "game.apk"
        apk.write_bytes(b"original apk")
        obb = source / f"main.42.{source_package}.obb"
        obb.write_bytes(obb_payload)
        request = BuildRequest(
            BundleDraft(
                source,
                apk,
                (obb,),
                package_name=source_package,
                version_code="42",
            ),
            target_package,
            root / "finished",
        )
        engine = self._engine(root)
        engine.runner = ExpansionPathToolRunner(obb.name)  # type: ignore[assignment]
        result = engine.build(request, log=logs.append if logs is not None else None)
        return result, obb

    def test_walkabout_pipeline_applies_and_reports_game_fixes(self) -> None:
        old = "com.MightyCoconut.WalkaboutMiniGolf"
        new = "com.mr.MightyCoconut.WalkaboutMiniGolf"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog = build_catalog([[old, "content"]])
            source_obb = root / "reference.obb"
            write_obb(source_obb, catalog)
            logs: list[str] = []

            payload = source_obb.read_bytes()
            result, obb = self._expansion_build(root, old, new, payload, logs)

            self.assertEqual(obb.read_bytes(), payload)
            self.assertEqual(result.obbs[0].name, f"main.42.{new}.obb")
            self.assertEqual(
                result.obbs[0].stat().st_size, len(payload) + 4 + len(new)
            )
            with zipfile.ZipFile(result.obbs[0]) as archive:
                self.assertIsNone(archive.testzip())
                internal_ids = resolve_catalog_internal_ids(
                    archive.read(CATALOG_ENTRY)
                )
            self.assertEqual(internal_ids, (f"{new}/content",))
            config_entry = "lib/arm64-v8a/libfrda.config.so"
            self.assertEqual(len(result.rewrite.game_fixes), 2)
            for line in result.rewrite.game_fixes:
                self.assertTrue(line.startswith("walkabout-mini-golf-"))
            self.assertIn(config_entry, result.rewrite.game_fixes[0])
            self.assertNotIn(config_entry, result.rewrite.preserved_files)
            report = json.loads(result.report.read_text(encoding="utf-8"))
            self.assertEqual(len(report["rewrite"]["game_fixes"]), 2)
            self.assertIn(
                "GAME-SPECIFIC FIXES",
                result.text_report.read_text(encoding="utf-8"),  # type: ignore[union-attr]
            )
            self.assertTrue(
                any("Rewrote the expansion-file path" in line for line in logs)
            )

    def test_other_packages_are_never_touched_by_game_fixes(self) -> None:
        old = "com.example.game"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload_path = root / "reference.obb"
            write_obb(payload_path, build_catalog([[old, "content"]]))
            payload = payload_path.read_bytes()

            result, _obb = self._expansion_build(
                root, old, "com.dev.example.game", payload
            )

            self.assertEqual(result.obbs[0].read_bytes(), payload)
            self.assertEqual(result.rewrite.game_fixes, ())
            report = json.loads(result.report.read_text(encoding="utf-8"))
            self.assertEqual(report["rewrite"]["game_fixes"], [])

    def test_other_package_with_unparseable_catalog_still_builds(self) -> None:
        old = "com.example.game"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload_path = root / "reference.obb"
            write_obb(payload_path, bytes(64))
            payload = payload_path.read_bytes()

            result, _obb = self._expansion_build(
                root, old, "com.dev.example.game", payload
            )

            self.assertEqual(result.obbs[0].read_bytes(), payload)
            self.assertEqual(result.rewrite.game_fixes, ())

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
            self.assertEqual(len(key_commands), 1)
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
