import tempfile
import unittest
from collections import namedtuple
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from quest_renamer.domain.models import BuildRequest, BundleDraft, DeviceSnapshot
from quest_renamer.infrastructure.older_firmware_patch import PATCH_ID
from quest_renamer.services.preflight import AutomaticPreflight, default_output_folder


class PreflightTests(unittest.TestCase):
    def test_source_replacement_accepts_a_parent_path_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            request = self._request(root)
            alias = root / "alias"
            try:
                alias.symlink_to(request.source.root, target_is_directory=True)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"Directory symlinks unavailable: {exc}")
            source = replace(request.source, root=alias, apk=alias / request.source.apk.name)
            replacement = replace(
                request, source=source, output_root=alias, replace_source=True
            )
            preflight = AutomaticPreflight(tools_ready=True)
            self.assertTrue(preflight.check(replacement).ready)
            (request.source.root / "notes.txt").touch()
            self.assertIn("notes.txt", preflight.check(replacement).summary)

    def test_skipped_game_data_does_not_consume_host_space_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            request = self._request(Path(temporary))
            package_dir = request.source.root / request.source.package_name
            package_dir.mkdir()
            with (package_dir / "large.dat").open("wb") as payload:
                payload.truncate(2 * 1024**3)
            usage = namedtuple("Usage", ["total", "used", "free"])(0, 0, 1024**3)
            preflight = AutomaticPreflight(tools_ready=True)
            with patch(
                "quest_renamer.services.preflight.shutil.disk_usage", return_value=usage
            ):
                self.assertFalse(preflight.check(request).ready)
                self.assertTrue(preflight.check(replace(request, copy_obbs=False)).ready)

    def _request(self, root: Path, *, output: Path | None = None) -> BuildRequest:
        source = root / "game"
        source.mkdir()
        apk = source / "game.apk"
        apk.write_bytes(b"apk")
        bundle = BundleDraft(source, apk, package_name="com.example.game")
        return BuildRequest(
            bundle,
            "com.dev.example.game",
            output or default_output_folder(source),
        )

    def test_ready_build_can_continue_with_disconnected_quest_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            request = self._request(Path(temporary))

            result = AutomaticPreflight(tools_ready=True).check(request)

            self.assertTrue(result.ready)
            self.assertTrue(result.warnings)
            self.assertIn("Quest capacity", result.summary)

    def test_default_output_uses_the_renamed_suffix(self) -> None:
        source = Path("/games/Example")

        self.assertEqual(default_output_folder(source), Path("/games/Example - Renamed"))

    def test_patch_only_build_can_keep_the_existing_package_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            request = self._request(Path(temporary))
            request = BuildRequest(
                request.source,
                request.source.package_name,
                request.output_root,
                patches=(PATCH_ID,),
            )

            result = AutomaticPreflight(tools_ready=True).check(request)

            self.assertTrue(result.ready)
            identity = next(check for check in result.checks if check.key == "identity")
            self.assertIn("patch-only", identity.detail)

    def test_output_inside_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = self._request(root, output=root / "game" / "output")

            result = AutomaticPreflight(tools_ready=True).check(request)

            self.assertFalse(result.ready)
            self.assertIn("inside the source", result.summary)

    def test_existing_nonempty_output_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "finished"
            output.mkdir()
            (output / "old.txt").touch()
            request = self._request(root, output=output)

            result = AutomaticPreflight(tools_ready=True).check(request)

            self.assertFalse(result.ready)
            self.assertIn("already exists", result.summary)

    def test_replace_source_mode_accepts_the_exact_nonempty_source_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = self._request(root)
            request = BuildRequest(
                request.source,
                request.package_name,
                request.source.root,
                replace_source=True,
            )

            result = AutomaticPreflight(tools_ready=True).check(request)

            self.assertTrue(result.ready)
            output_check = next(check for check in result.checks if check.key == "output")
            self.assertIn("swapped safely", output_check.detail)

    def test_replace_source_requires_obb_copying(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = self._request(root)
            obb = request.source.root / "main.1.com.example.game.obb"
            obb.write_bytes(b"obb")
            source = BundleDraft(
                request.source.root,
                request.source.apk,
                (obb,),
                package_name=request.source.package_name,
            )
            request = BuildRequest(
                source,
                request.package_name,
                source.root,
                copy_obbs=False,
                replace_source=True,
            )

            result = AutomaticPreflight(tools_ready=True).check(request)

            self.assertFalse(result.ready)
            self.assertIn("requires copying the game's OBBs", result.summary)

    def test_missing_tools_are_actionable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            request = self._request(Path(temporary))

            result = AutomaticPreflight(
                tools_ready=False,
                tool_problems=("Java runtime is missing",),
            ).check(request)

            self.assertFalse(result.ready)
            self.assertIn("Java runtime", result.summary)

    def test_low_quest_space_warns_without_blocking_a_build(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            request = self._request(Path(temporary))
            device = DeviceSnapshot(True, status="connected", free_bytes=1)

            result = AutomaticPreflight(tools_ready=True).check(request, device=device)

            self.assertTrue(result.ready)
            self.assertIn("may not fit", result.summary)

    def test_low_host_space_blocks_the_build(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            request = self._request(Path(temporary))
            with patch("quest_renamer.services.preflight.shutil.disk_usage") as disk_usage:
                disk_usage.return_value.free = 1

                result = AutomaticPreflight(tools_ready=True).check(request)

            self.assertFalse(result.ready)
            self.assertIn("does not have enough", result.summary)


if __name__ == "__main__":
    unittest.main()
