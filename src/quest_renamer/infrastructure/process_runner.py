"""Cancellable, shell-free subprocess execution with bounded diagnostics."""

from __future__ import annotations

import os
import queue
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from quest_renamer.domain.operations import CancellationToken, OperationCancelled


class CommandFailed(RuntimeError):
    def __init__(
        self, command: tuple[str, ...], returncode: int, output: tuple[str, ...]
    ) -> None:
        self.command = command
        self.returncode = returncode
        self.output = output
        detail = output[-1] if output else "No diagnostic output was produced."
        super().__init__(f"Command failed with exit code {returncode}: {detail}")


class CommandTimedOut(RuntimeError):
    def __init__(self, command: tuple[str, ...], timeout: float) -> None:
        self.command = command
        self.timeout = timeout
        super().__init__(f"Command exceeded its {timeout:g}-second safety deadline.")


@dataclass(frozen=True, slots=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int
    output: tuple[str, ...]


class ProcessRunner:
    def __init__(self, *, default_timeout: float = 30 * 60) -> None:
        if default_timeout <= 0:
            raise ValueError("The command deadline must be positive.")
        self.default_timeout = default_timeout

    def run(
        self,
        arguments: Sequence[str | Path],
        *,
        cwd: Path | None = None,
        token: CancellationToken | None = None,
        log: Callable[[str], None] | None = None,
        secret_values: set[str] | None = None,
        check: bool = True,
        timeout: float | None = None,
    ) -> CommandResult:
        command = tuple(str(value) for value in arguments)
        secrets = {value for value in (secret_values or set()) if value}
        token = token or CancellationToken()
        token.raise_if_cancelled()
        deadline_seconds = self.default_timeout if timeout is None else timeout
        if deadline_seconds <= 0:
            raise ValueError("The command deadline must be positive.")
        if log:
            log("$ " + " ".join("<hidden>" if value in secrets else value for value in command))

        on_windows = sys.platform.startswith("win")
        creationflags = 0
        if on_windows:
            creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) | int(
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
            start_new_session=not on_windows,
        )
        stdout = process.stdout
        if stdout is None:
            process.kill()
            raise RuntimeError("Process output pipe was not created.")
        lines: queue.Queue[str | None] = queue.Queue()

        def read_output() -> None:
            try:
                for line in stdout:
                    lines.put(line.rstrip())
            finally:
                lines.put(None)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        output: list[str] = []
        reader_finished = False
        started = time.monotonic()
        while process.poll() is None or not reader_finished:
            if token.is_cancelled() and process.poll() is None:
                self._stop_process_tree(process)
                reader.join(timeout=1)
                stdout.close()
                raise OperationCancelled("Operation cancelled.")
            if time.monotonic() - started >= deadline_seconds:
                if log:
                    log(f"Command timed out after {deadline_seconds:g} seconds.")
                self._stop_process_tree(process)
                reader.join(timeout=1)
                stdout.close()
                raise CommandTimedOut(command, deadline_seconds)
            try:
                line = lines.get(timeout=0.1)
            except queue.Empty:
                continue
            if line is None:
                reader_finished = True
                continue
            for secret in secrets:
                line = line.replace(secret, "<hidden>")
            if line:
                output.append(line)
                if len(output) > 500:
                    output.pop(0)
                if log:
                    log(line)
        stdout.close()
        returncode = process.wait()
        result = CommandResult(command, returncode, tuple(output))
        if check and returncode != 0:
            raise CommandFailed(command, returncode, result.output)
        return result

    @staticmethod
    def _stop_process_tree(process: subprocess.Popen[str]) -> None:
        if sys.platform.startswith("win"):
            subprocess.run(
                ("taskkill", "/PID", str(process.pid), "/T", "/F"),
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
            )
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            if sys.platform.startswith("win"):
                process.kill()
            else:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
            process.wait()
