"""Cancellable, shell-free subprocess execution with bounded diagnostics."""

from __future__ import annotations

import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from quest_renamer.domain.operations import CancellationToken, OperationCancelled

_STACK_NOISE = re.compile(r"^\s*(at |\.\.\. \d+ more|Caused by: |\s*$)")
_DIAGNOSTIC = re.compile(
    r"(Caused by:|Exception|Error\b|error:|E: |W: |brut\.|failed|Failed|cannot|Cannot)"
)


def describe_command_failure(output: tuple[str, ...]) -> str:
    """Pick the most meaningful line from tool output for a one-line error.

    Java tools end with a stack trace, so the literal last line is usually
    ``... 13 more``. Prefer the last line that reads like a diagnostic and skip
    stack frames; fall back to the last non-empty line.
    """
    if not output:
        return "No diagnostic output was produced."
    for line in reversed(output):
        if _STACK_NOISE.match(line):
            continue
        if _DIAGNOSTIC.search(line):
            return line.strip()
    for line in reversed(output):
        if line.strip() and not _STACK_NOISE.match(line):
            return line.strip()
    return output[-1].strip()


_JAVA_ENCODING_FLAGS = (
    "-Dfile.encoding=UTF-8",
    "-Dstdout.encoding=UTF-8",
    "-Dstderr.encoding=UTF-8",
    "-Dsun.stdout.encoding=UTF-8",
    "-Dsun.stderr.encoding=UTF-8",
)


def _with_java_encoding(command: tuple[str, ...]) -> tuple[str, ...]:
    """Force UTF-8 output for Java tools so non-ASCII paths survive on Windows.

    The flags go right after the executable, before ``-jar``; unknown system
    properties are ignored by every JDK, so older system Javas stay compatible.
    """
    if not command:
        return command
    executable = os.path.basename(command[0]).lower()
    if executable not in {"java", "java.exe", "javaw", "javaw.exe"}:
        return command
    if any(part.startswith("-Dfile.encoding=") for part in command[1:]):
        return command
    return (command[0], *_JAVA_ENCODING_FLAGS, *command[1:])


class CommandFailed(RuntimeError):
    def __init__(
        self, command: tuple[str, ...], returncode: int, output: tuple[str, ...]
    ) -> None:
        self.command = command
        self.returncode = returncode
        self.output = output
        detail = describe_command_failure(output)
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
        launch = _with_java_encoding(command)
        process = subprocess.Popen(
            launch,
            cwd=cwd,
            stdin=subprocess.DEVNULL,  # a prompting tool must fail, never hang
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
        output: deque[str] = deque(maxlen=500)
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
