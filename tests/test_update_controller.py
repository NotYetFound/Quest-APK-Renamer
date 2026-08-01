import time
import unittest

from PySide6.QtCore import QCoreApplication

from quest_renamer.domain.releases import (
    ReleaseCheckResult,
    ReleaseInfo,
    ReleaseVersion,
)
from quest_renamer.presentation.update_controller import UpdateController


class FakeChecker:
    def __init__(self, result: ReleaseCheckResult) -> None:
        self.result = result
        self.calls = 0

    def check(self) -> ReleaseCheckResult:
        self.calls += 1
        return self.result


class UpdateControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QCoreApplication.instance() or QCoreApplication([])

    def _wait(self, controller: UpdateController) -> None:
        deadline = time.monotonic() + 2
        while controller.isBusy and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.005)
        self.application.processEvents()

    def test_available_update_shows_banner_and_can_be_dismissed(self) -> None:
        latest = ReleaseInfo(
            tag="v1.5.0",
            name="1.5",
            url="https://example.invalid/release",
            version=ReleaseVersion(1, 5, 0),
        )
        checker = FakeChecker(ReleaseCheckResult(ReleaseVersion(1, 4, 0), latest))
        dismissed: list[str] = []
        controller = UpdateController(
            checker,
            current_version="1.4.0",
            preferences=lambda: (True, ""),
            save_dismissal=dismissed.append,
        )

        controller.startAutomatic()
        self._wait(controller)

        self.assertTrue(controller.hasUpdate)
        self.assertTrue(controller.bannerVisible)
        controller.dismiss()
        self.assertFalse(controller.bannerVisible)
        self.assertEqual(dismissed, ["v1.5.0"])

    def test_disabled_automatic_check_does_not_access_network(self) -> None:
        checker = FakeChecker(ReleaseCheckResult(ReleaseVersion(1, 4, 0)))
        controller = UpdateController(
            checker,
            current_version="1.4.0",
            preferences=lambda: (False, ""),
            save_dismissal=lambda _version: None,
        )

        controller.startAutomatic()

        self.assertEqual(checker.calls, 0)
        self.assertIn("off", controller.status.lower())

    def test_dismissed_update_stays_hidden_until_manual_check(self) -> None:
        latest = ReleaseInfo(
            tag="v1.5.0",
            name="1.5",
            url="https://example.invalid/release",
            version=ReleaseVersion(1, 5, 0),
        )
        checker = FakeChecker(ReleaseCheckResult(ReleaseVersion(1, 4, 0), latest))
        controller = UpdateController(
            checker,
            current_version="1.4.0",
            preferences=lambda: (True, "v1.5.0"),
            save_dismissal=lambda _version: None,
        )

        controller.startAutomatic()
        self._wait(controller)
        self.assertFalse(controller.bannerVisible)
        controller.checkNow()
        self._wait(controller)
        self.assertTrue(controller.bannerVisible)


if __name__ == "__main__":
    unittest.main()
