import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import quest_apk_renamer as app


class RenamerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def assertSamePath(self, actual, expected):
        self.assertEqual(Path(actual).resolve(), Path(expected).resolve())

    def assertSamePaths(self, actual, expected):
        self.assertEqual(
            [Path(path).resolve() for path in actual],
            [Path(path).resolve() for path in expected],
        )

    def test_package_validation(self):
        self.assertTrue(app.is_valid_package("com.example.game"))
        self.assertTrue(app.is_valid_package("studio_1.game2"))
        self.assertFalse(app.is_valid_package("onepart"))
        self.assertFalse(app.is_valid_package("com.example.bad-name"))
        self.assertFalse(app.is_valid_package("../not.a.package"))

    def test_bulk_suffix_is_appended_to_each_package(self):
        self.assertEqual(
            app.package_with_suffix("com.example.game", "a"),
            "com.example.gamea",
        )
        self.assertEqual(
            app.package_with_suffix("com.example.game", "_copy"),
            "com.example.game_copy",
        )
        with self.assertRaisesRegex(app.UserError, "bulk suffix"):
            app.package_with_suffix("com.example.game", ".bad")

    def test_multi_apk_picker_returns_every_selected_file(self):
        selected = (
            str(self.tmp_path / "First Game.apk"),
            str(self.tmp_path / "Second Game.apk"),
        )
        with (
            mock.patch.object(app.shutil, "which", return_value=None),
            mock.patch.object(
                app.filedialog,
                "askopenfilenames",
                return_value=selected,
            ) as picker,
        ):
            result = app.native_choose_apks(
                "Choose APKs",
                self.tmp_path,
            )

        self.assertEqual(result, list(selected))
        picker.assert_called_once_with(
            title="Choose APKs",
            initialdir=str(self.tmp_path),
            filetypes=[
                ("Android packages", "*.apk"),
                ("All files", "*"),
            ],
        )

    def test_kdialog_multi_apk_picker_reads_separate_output_lines(self):
        first = str(self.tmp_path / "First.apk")
        second = str(self.tmp_path / "Second.apk")
        completed = mock.Mock(
            returncode=0,
            stdout=f"{first}\n{second}\n",
        )
        with (
            mock.patch.object(
                app.shutil,
                "which",
                side_effect=lambda name: "/usr/bin/kdialog"
                if name == "kdialog"
                else None,
            ),
            mock.patch.object(
                app.subprocess,
                "run",
                return_value=completed,
            ) as runner,
        ):
            result = app.native_choose_apks("Choose APKs", self.tmp_path)

        self.assertEqual(result, [first, second])
        command = runner.call_args.args[0]
        self.assertIn("--multiple", command)
        self.assertIn("--separate-output", command)

    def test_discover_bundle_folders_scans_direct_children(self):
        first = self.tmp_path / "First Game"
        second = self.tmp_path / "Second Game"
        unrelated = self.tmp_path / "Notes"
        first.mkdir()
        second.mkdir()
        unrelated.mkdir()
        (first / "com.example.first.apk").write_bytes(b"first")
        (second / "com.example.second.apk").write_bytes(b"second")

        found, _skipped = app.discover_bundle_folders(self.tmp_path)

        self.assertSamePaths(found, [first, second])

    def test_staged_replacement_activates_output_after_completion(self):
        source = self.tmp_path / "Game"
        staged = self.tmp_path / ".Game-renamed-staging"
        source.mkdir()
        staged.mkdir()
        (source / "original.apk").write_bytes(b"original")
        (staged / "renamed.apk").write_bytes(b"renamed")
        (staged / "RENAMED-BUNDLE.txt").write_text(
            "complete\n",
            encoding="utf-8",
        )
        trashed = []

        def fake_trash(path):
            trashed.append((path / "original.apk").read_bytes())
            app.shutil.rmtree(path)
            return None

        output, backup, error = app.commit_staged_replacement(
            source,
            staged,
            fake_trash,
        )

        self.assertSamePath(output, source)
        self.assertIsNone(backup)
        self.assertIsNone(error)
        self.assertEqual(trashed, [b"original"])
        self.assertEqual((source / "renamed.apk").read_bytes(), b"renamed")
        self.assertFalse(staged.exists())

    def test_staged_replacement_keeps_backup_if_trash_fails(self):
        source = self.tmp_path / "Game"
        staged = self.tmp_path / ".Game-renamed-staging"
        source.mkdir()
        staged.mkdir()
        (source / "original.apk").write_bytes(b"original")
        (staged / "renamed.apk").write_bytes(b"renamed")
        (staged / "RENAMED-BUNDLE.txt").write_text(
            "complete\n",
            encoding="utf-8",
        )

        output, backup, error = app.commit_staged_replacement(
            source,
            staged,
            lambda _path: "simulated Trash failure",
        )

        self.assertSamePath(output, source)
        self.assertIsNotNone(backup)
        self.assertEqual(error, "simulated Trash failure")
        self.assertEqual((backup / "original.apk").read_bytes(), b"original")
        self.assertEqual((source / "renamed.apk").read_bytes(), b"renamed")

    def test_windows_app_data_uses_localappdata(self):
        with (
            mock.patch.object(app.sys, "platform", "win32"),
            mock.patch.dict(
                app.os.environ,
                {"LOCALAPPDATA": r"C:\Users\Test\AppData\Local"},
                clear=False,
            ),
        ):
            self.assertEqual(
                app.platform_app_data(),
                Path(r"C:\Users\Test\AppData\Local") / app.APP_NAME,
            )

    def test_macos_app_data_uses_application_support(self):
        with (
            mock.patch.object(app.sys, "platform", "darwin"),
            mock.patch.object(app.Path, "home", return_value=self.tmp_path),
        ):
            self.assertEqual(
                app.platform_app_data(),
                self.tmp_path
                / "Library"
                / "Application Support"
                / app.APP_NAME,
            )

    def test_macos_multi_apk_picker_uses_tk_native_dialog(self):
        selected = (
            str(self.tmp_path / "First.apk"),
            str(self.tmp_path / "Second.apk"),
        )
        with (
            mock.patch.object(app.sys, "platform", "darwin"),
            mock.patch.object(app.shutil, "which", return_value="/usr/bin/kdialog"),
            mock.patch.object(
                app.filedialog,
                "askopenfilenames",
                return_value=selected,
            ) as picker,
            mock.patch.object(app.subprocess, "run") as runner,
        ):
            result = app.native_choose_apks("Choose APKs", self.tmp_path)

        self.assertEqual(result, list(selected))
        picker.assert_called_once()
        runner.assert_not_called()

    def test_finds_containing_macos_app_bundle(self):
        executable = (
            self.tmp_path
            / "Quest APK Renamer.app"
            / "Contents"
            / "MacOS"
            / "Quest APK Renamer"
        )
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"binary")

        self.assertSamePath(
            app.find_macos_app_bundle(executable),
            self.tmp_path / "Quest APK Renamer.app",
        )
        self.assertIsNone(
            app.find_macos_app_bundle(self.tmp_path / "plain-executable")
        )

    def test_macos_application_detection_checks_both_applications_folders(self):
        user_application = self.tmp_path / "User Applications" / "App.app"
        system_application = self.tmp_path / "System Applications" / "App.app"
        self.assertFalse(
            app.macos_app_is_installed(
                None,
                user_application=user_application,
                system_application=system_application,
            )
        )
        user_application.mkdir(parents=True)
        self.assertTrue(
            app.macos_app_is_installed(
                None,
                user_application=user_application,
                system_application=system_application,
            )
        )

    def test_macos_trash_uses_finder_without_interpolating_the_path(self):
        completed = mock.Mock(returncode=0, stdout="", stderr="")
        target = self.tmp_path / 'unsafe " looking name'
        with (
            mock.patch.object(app.sys, "platform", "darwin"),
            mock.patch.object(
                app.subprocess,
                "run",
                return_value=completed,
            ) as runner,
        ):
            error = app.RenamerApp._move_path_to_trash(target)

        self.assertIsNone(error)
        command = runner.call_args.args[0]
        environment = runner.call_args.kwargs["env"]
        self.assertEqual(command[0], "/usr/bin/osascript")
        self.assertNotIn(str(target), " ".join(command))
        self.assertEqual(
            environment["QAR_TRASH_PATH"],
            str(target.resolve()),
        )

    def test_macos_applications_install_stages_and_verifies_the_bundle(self):
        source = self.tmp_path / "Mounted" / f"{app.APP_NAME}.app"
        (source / "Contents").mkdir(parents=True)
        (source / "Contents" / "Info.plist").write_text(
            "source",
            encoding="utf-8",
        )
        user_target = self.tmp_path / "Applications" / f"{app.APP_NAME}.app"
        system_target = self.tmp_path / "System" / f"{app.APP_NAME}.app"
        worker = object.__new__(app.RenamerApp)
        worker.launcher_button = mock.Mock()
        worker.status_var = mock.Mock()
        worker._append_log = mock.Mock()

        def fake_ditto(command, **_kwargs):
            destination = Path(command[2])
            (destination / "Contents").mkdir(parents=True)
            (destination / "Contents" / "Info.plist").write_text(
                "copied",
                encoding="utf-8",
            )
            return mock.Mock(returncode=0, stdout="", stderr="")

        with (
            mock.patch.object(app.sys, "platform", "darwin"),
            mock.patch.object(
                app,
                "find_macos_app_bundle",
                return_value=source,
            ),
            mock.patch.object(app, "MACOS_USER_APPLICATION", user_target),
            mock.patch.object(app, "MACOS_SYSTEM_APPLICATION", system_target),
            mock.patch.object(app.subprocess, "run", side_effect=fake_ditto),
            mock.patch.object(app.messagebox, "showinfo") as showinfo,
        ):
            app.RenamerApp.install_macos_application(worker)

        self.assertTrue((user_target / "Contents" / "Info.plist").is_file())
        worker.launcher_button.configure.assert_called_with(
            text="In Applications ✓"
        )
        showinfo.assert_called_once()

    def test_backup_reminder_setting_defaults_on_and_persists(self):
        settings_path = self.tmp_path / "settings.json"

        self.assertTrue(
            app.load_user_settings(settings_path)["ask_signing_key_backup"]
        )
        app.save_user_settings(
            {"ask_signing_key_backup": False},
            settings_path,
        )

        self.assertFalse(
            app.load_user_settings(settings_path)["ask_signing_key_backup"]
        )

    def test_disabled_backup_reminder_never_opens_prompt(self):
        worker = object.__new__(app.RenamerApp)
        worker.ask_key_backup_var = mock.Mock()
        worker.ask_key_backup_var.get.return_value = False
        worker.backup_signing_key = mock.Mock()

        with mock.patch.object(app.messagebox, "askyesno") as ask:
            app.RenamerApp._offer_signing_key_backup(worker)

        ask.assert_not_called()
        worker.backup_signing_key.assert_not_called()

    def test_enabled_backup_reminder_can_open_manual_backup(self):
        keystore = self.tmp_path / "key.jks"
        key_info = self.tmp_path / "signing-key.json"
        marker = self.tmp_path / "missing-backup-marker.json"
        keystore.write_bytes(b"key")
        key_info.write_text("{}\n", encoding="utf-8")
        worker = object.__new__(app.RenamerApp)
        worker.ask_key_backup_var = mock.Mock()
        worker.ask_key_backup_var.get.return_value = True
        worker.backup_signing_key = mock.Mock()

        with (
            mock.patch.object(app, "MANAGED_KEYSTORE", keystore),
            mock.patch.object(app, "MANAGED_KEY_INFO", key_info),
            mock.patch.object(app, "KEY_BACKUP_MARKER", marker),
            mock.patch.object(app.messagebox, "askyesno", return_value=True),
        ):
            app.RenamerApp._offer_signing_key_backup(worker)

        worker.backup_signing_key.assert_called_once_with()

    def test_release_version_metadata_stays_in_sync(self):
        project_root = Path(app.__file__).resolve().parent
        version = app.APP_VERSION
        expected_text = {
            "windows/installer.iss": f'#define MyAppVersion "{version}"',
            "windows/version-info.txt": f"u'ProductVersion', u'{version}'",
            ".github/workflows/windows-build.yml": f'APP_VERSION: "{version}"',
            ".github/workflows/macos-build.yml": f'APP_VERSION: "{version}"',
            ".github/workflows/linux-build.yml": f'APP_VERSION: "{version}"',
            "macos/quest-apk-renamer.spec": f'version="{version}"',
            "macos/build.sh": f'app_version="{version}"',
            "linux/build.sh": f'app_version="{version}"',
            "README.md": f"version-{version}-",
            "CHANGELOG.md": f"## [{version}]",
        }

        for relative_path, marker in expected_text.items():
            with self.subTest(path=relative_path):
                content = (project_root / relative_path).read_text(encoding="utf-8")
                self.assertIn(marker, content)

    def test_release_screenshots_are_present(self):
        project_root = Path(app.__file__).resolve().parent
        for name in (
            "main-window.png",
            "advanced-options.png",
            "bulk-tools.png",
        ):
            with self.subTest(screenshot=name):
                content = (project_root / "docs" / "screenshots" / name).read_bytes()
                self.assertTrue(content.startswith(b"\x89PNG\r\n\x1a\n"))
                self.assertGreater(len(content), 10_000)

    def test_posix_build_scripts_are_executable(self):
        if os.name == "nt":
            self.skipTest("Windows does not preserve POSIX executable mode bits")
        project_root = Path(app.__file__).resolve().parent
        for relative_path in (
            "macos/build.sh",
            "macos/bootstrap-dependencies.sh",
            "linux/build.sh",
            "linux/bootstrap-dependencies.sh",
            "linux/install.sh",
            "linux/uninstall.sh",
        ):
            with self.subTest(path=relative_path):
                mode = (project_root / relative_path).stat().st_mode
                self.assertTrue(mode & 0o111)

    def test_bulk_rename_worker_runs_jobs_sequentially(self):
        worker = object.__new__(app.RenamerApp)
        worker.cancel_event = threading.Event()
        worker.events = app.queue.Queue()
        calls = []
        jobs = []
        for index in range(2):
            root = self.tmp_path / f"Game {index}"
            root.mkdir()
            apk = root / f"com.example.game{index}.apk"
            apk.write_bytes(b"apk")
            bundle = app.BundleInfo(
                apk=apk,
                root=root,
                obbs=[],
                release_manifest=None,
                package_name=f"com.example.game{index}",
                version_code="1",
                game_name=f"Game {index}",
            )
            jobs.append(
                (
                    bundle,
                    f"com.example.game{index}a",
                    self.tmp_path / f"Output {index}",
                )
            )

        def fake_rename(
            _old,
            new,
            _version,
            output,
            _copy_obbs,
            _should_sign,
            _replace_source,
            **_kwargs,
        ):
            calls.append(new)
            return output

        worker._rename_worker = fake_rename
        app.RenamerApp._bulk_rename_worker(
            worker,
            jobs,
            False,
            True,
            True,
        )

        self.assertEqual(
            calls,
            ["com.example.game0a", "com.example.game1a"],
        )
        events = list(worker.events.queue)
        overview = next(payload for kind, payload in events if kind == "bulk_complete")
        self.assertEqual(
            [result["success"] for result in overview["results"]],
            [True, True],
        )

    def test_bulk_install_worker_continues_after_one_failure(self):
        worker = object.__new__(app.RenamerApp)
        worker.cancel_event = threading.Event()
        worker.events = app.queue.Queue()
        bundles = []
        for index in range(2):
            root = self.tmp_path / f"Install {index}"
            root.mkdir()
            apk = root / f"com.example.install{index}.apk"
            apk.write_bytes(b"apk")
            bundles.append(
                app.BundleInfo(
                    apk=apk,
                    root=root,
                    obbs=[],
                    release_manifest=None,
                    package_name=f"com.example.install{index}",
                    version_code="1",
                    game_name=f"Install {index}",
                )
            )
        calls = []
        worker._package_conflict_on_connected_quest = lambda _package: False

        def fake_install(bundle, *_args, **_kwargs):
            calls.append(bundle.package_name)
            if bundle.package_name.endswith("0"):
                raise app.UserError("simulated failure")
            return {"source_removed": False, "cleanup_error": None}

        worker._quest_install_worker = fake_install
        app.RenamerApp._bulk_install_worker(worker, bundles, False)

        self.assertEqual(
            calls,
            ["com.example.install0", "com.example.install1"],
        )
        events = list(worker.events.queue)
        overview = next(payload for kind, payload in events if kind == "bulk_complete")
        self.assertEqual(
            [result["success"] for result in overview["results"]],
            [False, True],
        )

    def test_install_cleanup_runs_only_after_full_verification(self):
        root = self.tmp_path / "Finished"
        root.mkdir()
        apk = root / "com.example.finished.apk"
        apk.write_bytes(b"apk")
        (root / "RENAMED-BUNDLE.txt").write_text(
            "complete\n",
            encoding="utf-8",
        )
        bundle = app.BundleInfo(
            apk=apk,
            root=root,
            obbs=[],
            release_manifest=None,
            package_name="com.example.finished",
            version_code="1",
            game_name="Finished",
        )
        worker = object.__new__(app.RenamerApp)
        worker.cancel_event = threading.Event()
        worker._run_command = lambda *_args, **_kwargs: None
        worker._copy_obbs_to_quest = lambda *_args, **_kwargs: []
        worker._move_path_to_trash = mock.Mock(return_value=None)
        adb_results = [
            mock.Mock(
                returncode=0,
                stdout="List of devices attached\nQUEST123 device model:Quest_3\n",
                stderr="",
            ),
            mock.Mock(returncode=1, stdout="", stderr=""),
            mock.Mock(
                returncode=0,
                stdout="package:/data/app/com.example.finished/base.apk\n",
                stderr="",
            ),
        ]

        with (
            mock.patch.object(app, "find_adb", return_value=Path("/fake/adb")),
            mock.patch.object(app.subprocess, "run", side_effect=adb_results),
        ):
            outcome = app.RenamerApp._quest_install_worker(
                worker,
                bundle,
                False,
                True,
                emit_events=False,
            )

        worker._move_path_to_trash.assert_called_once_with(root)
        self.assertTrue(outcome["source_removed"])

    def test_install_cleanup_is_skipped_when_obb_verification_fails(self):
        root = self.tmp_path / "Finished"
        root.mkdir()
        apk = root / "com.example.finished.apk"
        apk.write_bytes(b"apk")
        obb = root / "main.1.com.example.finished.obb"
        obb.write_bytes(b"obb")
        (root / "RENAMED-BUNDLE.txt").write_text(
            "complete\n",
            encoding="utf-8",
        )
        bundle = app.BundleInfo(
            apk=apk,
            root=root,
            obbs=[obb],
            release_manifest=None,
            package_name="com.example.finished",
            version_code="1",
            game_name="Finished",
        )
        worker = object.__new__(app.RenamerApp)
        worker.cancel_event = threading.Event()
        worker._run_command = lambda *_args, **_kwargs: None
        worker._copy_obbs_to_quest = lambda *_args, **_kwargs: [obb]
        worker._move_path_to_trash = mock.Mock(return_value=None)
        adb_results = [
            mock.Mock(
                returncode=0,
                stdout="List of devices attached\nQUEST123 device model:Quest_3\n",
                stderr="",
            ),
            mock.Mock(returncode=1, stdout="", stderr=""),
        ]

        with (
            mock.patch.object(app, "find_adb", return_value=Path("/fake/adb")),
            mock.patch.object(app.subprocess, "run", side_effect=adb_results),
            self.assertRaisesRegex(app.UserError, "OBB transfer"),
        ):
            app.RenamerApp._quest_install_worker(
                worker,
                bundle,
                False,
                True,
                emit_events=False,
            )

        worker._move_path_to_trash.assert_not_called()

    def test_bundled_tool_hashes_match_metadata(self):
        project_root = Path(app.__file__).resolve().parent
        metadata = app.json.loads(
            (project_root / "tools" / "versions.json").read_text(encoding="utf-8")
        )
        tool_files = {
            "apktool": project_root / "tools" / "apktool.jar",
            "uber-apk-signer": project_root / "tools" / "uber-apk-signer.jar",
        }

        for name, path in tool_files.items():
            with self.subTest(tool=name):
                self.assertTrue(path.is_file())
                self.assertEqual(app.sha256_file(path), metadata[name]["sha256"])

    def test_format_size_uses_expected_units(self):
        self.assertEqual(app.format_size(999), "999 B")
        self.assertEqual(app.format_size(1_500_000), "1.5 MB")
        self.assertEqual(app.format_size(3_400_000_000), "3.4 GB")

    def test_desktop_entry_uses_this_app_folder(self):
        entry = app.desktop_entry_text()

        self.assertIn(f'Exec="{app.SCRIPT_DIR / "launch.sh"}" %f', entry)
        self.assertIn(f"Icon={app.SCRIPT_DIR / 'assets/quest-apk-renamer.svg'}", entry)
        self.assertIn("Keywords=Quest;APK;OBB;Android;Sideload;", entry)

    def test_drag_and_drop_runtime_is_bundled(self):
        self.assertTrue(app.DND_AVAILABLE)

    def test_parse_adb_devices(self):
        connected, unavailable = app.parse_adb_devices(
            "* daemon started successfully\n"
            "List of devices attached\n"
            "QUEST123 device usb:1-2 model:Quest_3\n"
            "PHONE456 unauthorized usb:1-3\n"
        )

        self.assertEqual(connected, ["QUEST123"])
        self.assertEqual(unavailable, ["PHONE456 (unauthorized)"])

    def test_parse_adb_model(self):
        output = (
            "List of devices attached\n"
            "QUEST123 device usb:1-2 product:eureka model:Quest_3 device:eureka\n"
        )
        self.assertEqual(app.parse_adb_model(output, "QUEST123"), "Quest 3")
        self.assertEqual(app.parse_adb_model(output, "UNKNOWN"), "Quest")

    def test_parse_android_storage(self):
        output = (
            "Filesystem     1K-blocks     Used Available Use% Mounted on\n"
            "/dev/fuse       125000000 25000000 100000000  20% /storage/emulated\n"
        )
        self.assertEqual(
            app.parse_df_storage(output),
            (100_000_000 * 1024, 125_000_000 * 1024),
        )
        self.assertIsNone(app.parse_df_storage("storage unavailable\n"))

    def test_package_install_detection(self):
        self.assertTrue(
            app.package_is_installed(
                0, "package:/data/app/~~abc/com.example.game/base.apk\n"
            )
        )
        self.assertFalse(app.package_is_installed(1, ""))
        self.assertFalse(app.package_is_installed(0, ""))

    def test_detect_bundle_from_release_manifest(self):
        apk = self.tmp_path / "com.example.game.apk"
        apk.write_bytes(b"test")
        obb_dir = self.tmp_path / "com.example.game"
        obb_dir.mkdir()
        obb = obb_dir / "main.42.com.example.game.obb"
        obb.write_bytes(b"obb")
        (self.tmp_path / "release.manifest").write_text(
            "\ufeff#VRPRELEASEMANIFEST 1.0\n"
            "Game Name;Release Name;Package Name;Version Code;Last Updated;Size (MB);Downloads;Rating;Rating Count\n"
            "Example Game;Example Release;com.example.game;42;2026-01-01 00:00 UTC;1;0;0;0\n",
            encoding="utf-8",
        )

        bundle = app.detect_bundle(apk)

        self.assertEqual(bundle.package_name, "com.example.game")
        self.assertEqual(bundle.version_code, "42")
        self.assertEqual(bundle.game_name, "Example Game")
        self.assertSamePaths(bundle.obbs, [obb])

    def test_detect_whole_game_folder(self):
        apk = self.tmp_path / "com.example.game.apk"
        apk.write_bytes(b"test")
        obb_dir = self.tmp_path / "com.example.game"
        obb_dir.mkdir()
        (obb_dir / "main.42.com.example.game.obb").write_bytes(b"obb")

        bundle = app.detect_bundle_from_folder(self.tmp_path)

        self.assertSamePath(bundle.root, self.tmp_path)
        self.assertSamePath(bundle.apk, apk)
        self.assertEqual(bundle.package_name, "com.example.game")
        self.assertEqual(bundle.version_code, "42")

    def test_working_space_estimate_includes_apk_obb_and_buffer(self):
        apk = self.tmp_path / "com.example.game.apk"
        apk.write_bytes(b"a" * 100)
        obb = self.tmp_path / "main.1.com.example.game.obb"
        obb.write_bytes(b"b" * 1000)
        bundle = app.BundleInfo(
            apk=apk,
            root=self.tmp_path,
            obbs=[obb],
            release_manifest=None,
            package_name="com.example.game",
            version_code="1",
            game_name="Example",
        )

        self.assertEqual(
            app.required_working_space(bundle),
            int(100 * 5 + 1000 * 1.1 + 500_000_000),
        )
        self.assertEqual(
            app.required_quest_space(bundle),
            int(100 * 2 + 1000 * 1.05 + 250_000_000),
        )

    def test_managed_output_requires_marker(self):
        self.assertFalse(app.is_managed_output(self.tmp_path))
        (self.tmp_path / "RENAMED-BUNDLE.txt").write_text("managed\n")
        self.assertTrue(app.is_managed_output(self.tmp_path))

    def test_command_progress_parser(self):
        updates = []
        app.RenamerApp._run_command(
            [app.sys.executable, "-c", "print('transfer 42%')"],
            log=lambda _message: None,
            progress=updates.append,
        )
        self.assertEqual(updates, [42])

    def test_obb_copy_honors_cancellation_before_adb_changes(self):
        apk = self.tmp_path / "com.example.game.apk"
        apk.write_bytes(b"apk")
        obb = self.tmp_path / "main.1.com.example.game.obb"
        obb.write_bytes(b"obb")
        bundle = app.BundleInfo(
            apk=apk,
            root=self.tmp_path,
            obbs=[obb],
            release_manifest=None,
            package_name="com.example.game",
            version_code="1",
            game_name="Example",
        )
        worker = object.__new__(app.RenamerApp)
        worker.cancel_event = threading.Event()
        worker.cancel_event.set()
        worker._run_command = lambda *_args, **_kwargs: self.fail(
            "ADB command ran after cancellation"
        )

        with self.assertRaises(app.OperationCancelled):
            worker._copy_obbs_to_quest(
                ["adb", "-s", "QUEST123"],
                bundle,
                [obb],
                log=lambda _message: None,
                progress=lambda _percent, _message: None,
                completed_remote=[],
            )

    def test_obb_copy_returns_only_failed_files_for_retry(self):
        apk = self.tmp_path / "com.example.game.apk"
        apk.write_bytes(b"apk")
        obb = self.tmp_path / "main.1.com.example.game.obb"
        obb.write_bytes(b"obb")
        bundle = app.BundleInfo(
            apk=apk,
            root=self.tmp_path,
            obbs=[obb],
            release_manifest=None,
            package_name="com.example.game",
            version_code="1",
            game_name="Example",
        )
        worker = object.__new__(app.RenamerApp)
        worker.cancel_event = threading.Event()

        def run_command(args, **_kwargs):
            if "push" in args:
                raise app.UserError("simulated transfer failure")

        worker._run_command = run_command
        failed = worker._copy_obbs_to_quest(
            ["adb", "-s", "QUEST123"],
            bundle,
            [obb],
            log=lambda _message: None,
            progress=lambda _percent, _message: None,
            completed_remote=[],
        )

        self.assertEqual(failed, [obb])

    def test_folder_with_multiple_apks_explains_problem(self):
        (self.tmp_path / "one.apk").write_bytes(b"one")
        (self.tmp_path / "two.apk").write_bytes(b"two")

        with self.assertRaisesRegex(app.UserError, "More than one APK"):
            app.detect_bundle_from_folder(self.tmp_path)

    def test_replace_package_references_only_changes_technical_files(self):
        decoded = self.tmp_path / "decoded"
        decoded.mkdir()
        text = decoded / "AndroidManifest.xml"
        text.write_text(
            '<manifest package="com.old.game">com/old/game/Main</manifest>',
            encoding="utf-8",
        )
        binary = decoded / "asset.bin"
        original = b"\x00com.old.game\xff"
        binary.write_bytes(original)
        assets = decoded / "assets"
        assets.mkdir()
        game_text = assets / "dialogue.json"
        original_text = b'{"debug": "com.old.game", "line": "Keep this text"}'
        game_text.write_bytes(original_text)

        messages = []
        count = app.replace_package_references(
            decoded, "com.old.game", "com.new.game", log=messages.append
        )

        self.assertEqual(count, 2)
        self.assertIn("com.new.game", text.read_text(encoding="utf-8"))
        self.assertIn("com/new/game/Main", text.read_text(encoding="utf-8"))
        self.assertEqual(binary.read_bytes(), original)
        self.assertEqual(game_text.read_bytes(), original_text)
        self.assertTrue(
            any("deliberately preserved unchanged" in line for line in messages)
        )

    def test_build_release_manifest(self):
        apk = self.tmp_path / "com.new.game.apk"
        apk.write_bytes(b"apk")
        obb = self.tmp_path / "com.new.game" / "main.42.com.new.game.obb"
        obb.parent.mkdir()
        obb.write_bytes(b"obb")

        manifest = app.build_release_manifest(
            source_manifest=None,
            output_root=self.tmp_path,
            new_package="com.new.game",
            game_name="New Game",
            version_code="42",
            apk_output=apk,
            obb_outputs=[obb],
        )
        content = manifest.read_text(encoding="utf-8-sig")

        self.assertIn("New Game;", content)
        self.assertIn(";com.new.game;42;", content)
        self.assertIn("f;./com.new.game.apk;3", content)
        self.assertIn(
            "f;./com.new.game/main.42.com.new.game.obb;3", content
        )


if __name__ == "__main__":
    unittest.main()
