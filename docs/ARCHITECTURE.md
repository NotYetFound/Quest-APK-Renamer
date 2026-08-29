# Architecture

Quest APK Renamer is split by responsibility so new patches, install modes, and platforms do
not enlarge a single application class.

## Dependency direction

```text
QML interface
    ↓
Presentation controllers
    ↓
Application workflows → Service protocols
    ↓                       ↓
Domain models          Infrastructure adapters
```

- `domain` contains typed data and deterministic rules. It never imports Qt or launches tools.
- `services` defines capabilities required by workflows. Protocols keep implementations fakeable.
- `infrastructure` talks to files, processes, ADB, operating systems, and the bundled Java tools.
- `presentation` converts typed state into Qt properties/signals. It owns no build algorithms.
- The dashboard and bulk queue use separate presentation controllers and share the same typed
  engine adapters. Their busy-state providers prevent both workspaces from starting expensive
  operations at the same time.
- The Library controller presents the local signing-key vault separately from a generation-guarded
  live headset inventory. The JSON store owns recoverable atomic serialization; the main workflow
  only asks it to match, record, or retrieve profiles.
- Library import/export runs off the UI thread. Portable archives are size-bounded, reject unsafe
  paths, verify artifact hashes before activation, and copy imported private files into unique
  local identity folders rather than trusting paths from another computer.
- The detailed Inspector has its own controller and full-decode adapter. Normal Dashboard analysis
  remains manifest-only; deeper signature, resource, hash, and reference scans run only when the
  user opens the Inspector.
- `qml` controls layout and interaction but never constructs shell commands or changes source data.

## Threading

- QML and controller property mutation stay on the Qt main thread.
- Device, APK, build, install, hashing, and network work run outside the UI thread.
- Worker results return as typed snapshots or results through queued Qt signals.
- Bulk jobs execute sequentially in one worker and publish per-item snapshots through a
  `QAbstractListModel`; a failed item is recorded before the next item starts.
- Cancellation is cooperative and occurs at documented safe boundaries. Bundle installs finish
  the active APK or OBB command, then stop before the next file.

## Filesystem safety

- Source bundles are read-only unless an explicit replacement job is selected.
- Replacement jobs build in a sibling staging directory and activate only after verification.
  Activation renames the source to a temporary backup, swaps the verified bundle into the exact
  source path, and rolls back if the second rename fails. The backup then moves to the platform
  Trash; if Trash is unavailable it becomes a visible recovery folder.
- Settings and reports use temporary-file replacement.
- Optional post-install cleanup applies to the finished folder that was just installed, not an
  unrelated original. It runs only after APK and OBB verification and requires the app's build
  report, a direct-child APK, and a non-home/non-root path. Source replacement and post-install
  cleanup remain independent settings.
- Signing-key backups contain the canonical identity, every cert-lineage identity, and recorded
  hashes. A new lineage key makes the prior backup marker stale. Restores validate the complete
  backup before asking for replacement confirmation, activate through a sibling staging folder,
  and preserve the previous identity in a recovery folder.
- Quest updates stage changed OBBs under transaction names, reuse identical remote data, and keep
  replacement backups until APK and OBB verification succeeds. Cleanup targets only versioned
  expansion files or names previously recorded as app-managed; unknown files remain untouched.

## Interaction policy

- Routine status, progress, success, and recoverable errors stay inline.
- Modal decisions use one compact QML component with a short title, a short explanation, and two
  actions at most.
- A popup is reserved for a decision that cannot be made safely on the user's behalf, such as
  updating an existing package, replacing a signing identity, or removing partial output.

## Platform policy

- Use standard Windows, macOS, and freedesktop/XDG locations.
- Never form shell command strings; process arguments are always sequences.
- Platform discovery is ordered: explicit override, bundled runtime, SDK locations, known tools,
  then `PATH`.
- Every supported platform receives a packaged GUI smoke test, not only a source test.

## Efficiency policy

- QML-facing collections cache derived rows and use virtualized views; filesystem/key validation
  runs when backing state changes rather than on every property read.
- Device inventory avoids per-package ADB calls. Current firmware returns version codes in one
  package-manager request, with one bulk `dumpsys` fallback for older firmware.
- Large OBBs are streamed for hashing, and unchanged local hashes may be reused only while the
  resolved path, byte size, and nanosecond modification time still match.
- Nontechnical decoded APK files are scanned in bounded chunks. Technical files are loaded only
  when they may actually be rewritten.
- A package reference is matched as a whole token (`infrastructure/reference_scanner.py`):
  `com.example.game` and its sub-packages match, `com.example.gamepad` and
  `org.foo.com.example.game` do not. The Inspector preview and the rewrite share this rule.
- Only the *application ID* is rewritten. Identity references (the bare package, provider
  authorities, custom permissions, intent actions and other lower-case / ALL_CAPS
  continuations) change; Java namespace references (`Lcom/example/game/Main;`, `com/example/game`,
  and dotted class names such as `com.example.game.ui.Main`) never do, because native libraries
  bind to Java classes by their original names (`Java_com_example_game_Main_init` exports and
  `FindClass`). Relative manifest component names are expanded against the original package
  first so they keep pointing at those classes (`infrastructure/package_rewriter.py`).
- Native libraries are scanned for the JNI export prefix (`Java_<mangled package>_`). The
  legacy "also rename Java packages" mode is refused when any is found; the default mode records
  them in the report. An optional display name / suffix is applied to the manifest label or the
  referenced `<string>` in every `values*` folder (`infrastructure/app_label.py`).
- Scan patterns start with the literal package so `re` can use its prefix scan; boundary
  look-behind is checked in Python. This keeps 400 MB decodes under a second instead of ~30 s.
- The installer prunes obsolete OBBs only when the bundle supplied the complete OBB set (or a
  retry was given the full set of names); APK-only installs never touch existing OBBs. Remote
  listings use one `stat` call per phase and remote digests are cached per transfer.
- Frozen-package trimming is accepted only after the portable executable and AppImage both pass
  the same offscreen QML launch test; native dialog, display, rendering, and image plugins remain.
