"""Keep Qt test controllers alive for their queued worker callbacks.

The real app parents these controllers to its QML engine. Tests often omit a
parent and replace their last Python reference while timers/signals are queued.
Mirror application ownership so collection cannot destroy them mid-dispatch.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from PySide6.QtCore import QCoreApplication

from quest_renamer.presentation.app_controller import AppController


@pytest.fixture(scope="session", autouse=True)
def own_test_controllers() -> Iterator[None]:
    initialize = AppController.__init__

    def initialize_owned(self: AppController, *args: Any, **kwargs: Any) -> None:
        if kwargs.get("parent") is None:
            kwargs["parent"] = QCoreApplication.instance()
        initialize(self, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(AppController, "__init__", initialize_owned)
        yield
