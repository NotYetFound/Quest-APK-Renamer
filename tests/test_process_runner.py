import sys
import threading
import time
import unittest

from quest_renamer.infrastructure.process_runner import (
    CancellationToken,
    CommandFailed,
    OperationCancelled,
    ProcessRunner,
)


class ProcessRunnerTests(unittest.TestCase):
    def test_output_is_streamed_and_returned(self) -> None:
        logged: list[str] = []
        result = ProcessRunner().run(
            [sys.executable, "-c", "print('ready')"],
            log=logged.append,
        )
        self.assertEqual(result.output, ("ready",))
        self.assertEqual(result.returncode, 0)
        self.assertTrue(any("ready" in line for line in logged))

    def test_secrets_are_removed_from_command_and_output(self) -> None:
        secret = "do-not-log-this"
        logged: list[str] = []
        result = ProcessRunner().run(
            [sys.executable, "-c", "import sys; print(sys.argv[1])", secret],
            log=logged.append,
            secret_values={secret},
        )
        combined = "\n".join((*logged, *result.output))
        self.assertNotIn(secret, combined)
        self.assertIn("<hidden>", combined)

    def test_nonzero_exit_raises_a_typed_error(self) -> None:
        with self.assertRaises(CommandFailed) as raised:
            ProcessRunner().run([sys.executable, "-c", "print('reason'); raise SystemExit(4)"])
        self.assertEqual(raised.exception.returncode, 4)
        self.assertEqual(raised.exception.output, ("reason",))

    def test_cancellation_terminates_a_running_process(self) -> None:
        token = CancellationToken()
        timer = threading.Thread(
            target=lambda: (time.sleep(0.15), token.cancel()),
            daemon=True,
        )
        timer.start()
        started = time.monotonic()
        with self.assertRaises(OperationCancelled):
            ProcessRunner().run(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                token=token,
            )
        self.assertLess(time.monotonic() - started, 3)


if __name__ == "__main__":
    unittest.main()
