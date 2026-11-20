"""Registry of per-game fixes, keyed by SOURCE package ID."""

from __future__ import annotations

from quest_renamer.infrastructure.game_fixes.base import (
    DecodedApkFixResult,
    GameFix,
    GameFixContext,
    GameFixError,
)
from quest_renamer.infrastructure.game_fixes.walkabout_mini_golf import (
    WalkaboutMiniGolfFix,
)

GAME_FIXES: tuple[GameFix, ...] = (WalkaboutMiniGolfFix(),)


def fixes_for(source_package: str) -> tuple[GameFix, ...]:
    """Fixes registered for exactly this source package ID (case-sensitive)."""
    return tuple(fix for fix in GAME_FIXES if source_package in fix.source_packages)


__all__ = [
    "GAME_FIXES",
    "DecodedApkFixResult",
    "GameFix",
    "GameFixContext",
    "GameFixError",
    "fixes_for",
]
