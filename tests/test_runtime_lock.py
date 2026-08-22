import json
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path


class RuntimeLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).parents[1]
        self.lock_path = self.root / "packaging" / "runtime-lock.json"

    def test_every_supported_runtime_is_pinned(self) -> None:
        lock = json.loads(self.lock_path.read_text(encoding="utf-8"))
        expected = {"linux-x86_64", "macos-arm64", "macos-x86_64", "windows-x86_64"}
        for component in ("temurin", "platform_tools"):
            self.assertEqual(set(lock[component]), expected)
            for artifact in lock[component].values():
                self.assertTrue(artifact["url"].startswith("https://"))
                self.assertNotIn("latest", artifact["url"])
                self.assertRegex(artifact["sha256"], r"^[0-9a-f]{64}$")

    def test_reader_returns_shell_safe_tab_separated_fields(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(self.root / "scripts" / "read_runtime_lock.py"),
                str(self.lock_path),
                "temurin",
                "linux-x86_64",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        url, checksum, version = completed.stdout.strip().split("\t")
        self.assertIn("21.0.12", url)
        self.assertEqual(len(checksum), 64)
        self.assertEqual(version, "21.0.12+8")

    def test_release_python_bootstrap_versions_are_exact(self) -> None:
        project = tomllib.loads((self.root / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertTrue(
            all("==" in requirement for requirement in project["build-system"]["requires"])
        )
        requirements = (
            self.root / "packaging" / "requirements-build.txt"
        ).read_text(encoding="utf-8").splitlines()
        self.assertTrue(requirements)
        self.assertTrue(all("==" in line for line in requirements if line.strip()))
        for script in (
            self.root / "packaging" / "linux" / "build.sh",
            self.root / "packaging" / "macos" / "build.sh",
            self.root / "packaging" / "windows" / "build.ps1",
        ):
            self.assertNotIn("pip install --upgrade pip", script.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
