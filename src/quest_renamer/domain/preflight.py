"""Immutable readiness results for a proposed APK build."""

from __future__ import annotations

from dataclasses import dataclass

from quest_renamer.domain.models import CheckState, ReadinessCheck


@dataclass(frozen=True, slots=True)
class PreflightResult:
    checks: tuple[ReadinessCheck, ...]
    host_required_bytes: int
    quest_required_bytes: int

    @property
    def ready(self) -> bool:
        return all(check.state is not CheckState.FAILED for check in self.checks)

    @property
    def warnings(self) -> tuple[ReadinessCheck, ...]:
        return tuple(check for check in self.checks if check.state is CheckState.WARNING)

    @property
    def failures(self) -> tuple[ReadinessCheck, ...]:
        return tuple(check for check in self.checks if check.state is CheckState.FAILED)

    @property
    def summary(self) -> str:
        if self.failures:
            return self.failures[0].detail or self.failures[0].label
        if self.warnings:
            return self.warnings[0].detail or self.warnings[0].label
        return "Ready to build. Source files will not be changed."
