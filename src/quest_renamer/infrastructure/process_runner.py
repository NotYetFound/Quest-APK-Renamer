"""Cancellable, shell-free subprocess execution with bounded diagnostics."""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
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


@dataclass(frozen=True, slots=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int
    output: tuple[str, ...]


class ProcessRunner:
    def run(
        self,
        arguments: Sequence[str | Path],
        *,
        cwd: Path | None = None,
        token: CancellationToken | None = None,
        log: Callable[[str], None] | None = None,
        secret_values: set[str] | None = None,
        check: bool = True,
    ) -> CommandResult:
        command = tuple(str(value) for value in arguments)
        secrets = {value for value in (secret_values or set()) if value}
        token = token or CancellationToken()
        token.raise_if_cancelled()
        if log:
            log("$ " + " ".join("<hidden>" if value in secrets else value for value in command))

        creationflags = (
            int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if sys.platform.startswith("win")
            else 0
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
        while process.poll() is None or not reader_finished:
            if token.is_cancelled() and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                reader.join(timeout=1)
                stdout.close()
                raise OperationCancelled("Operation cancelled.")
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
