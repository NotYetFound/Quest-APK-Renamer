# Contributing

Thank you for helping improve Quest APK Renamer.

## Before opening an issue

- Search existing issues first.
- Remove game names, usernames, serial numbers, and private paths from logs.
- Never upload APKs, OBBs, signing keys, `signing-key.json`, or paid game data.
- Confirm that you own or are authorized to modify the software involved.

Bug reports should include the operating system, app version, Quest model,
the stage that failed, and a sanitized copy of **Show details** output.

## Development setup

Quest APK Renamer requires Python 3.10 or newer. TkinterDnD2 is vendored for the
desktop runtime.

Run the test suite before and after a change:

```bash
python3 -m unittest discover -s tests -v
```

Launch the app from the repository:

```bash
./launch.sh
```

Platform packaging instructions are in
[windows/README.md](windows/README.md),
[macos/README.md](macos/README.md), and
[linux/README.md](linux/README.md).

## Pull requests

- Keep changes focused and explain their user-visible effect.
- Add or update tests for behavior changes.
- Update the README and changelog when the workflow or UI changes.
- Preserve the default non-destructive workflow and the staged, rollback-safe
  guarantees of opt-in source replacement.
- Do not introduce entitlement bypasses, store piracy features, credential
  extraction, or broad binary patching.
- Do not commit downloaded game bundles, signing material, or generated build
  output.

By submitting a contribution, you confirm that you have the right to submit it
and agree that it may be distributed under the project's MIT License.
