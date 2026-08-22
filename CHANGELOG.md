# Changelog

All notable changes to Quest APK Renamer are recorded here.

## Unreleased

## [1.4.6] - 2026-08-22

### Added

- Wireless ADB: connect to a headset by address (or a pasted `adb connect` line), switch a USB-attached
  Quest to wireless ADB with one click, and a saved-Quests list (name, address, last connection) with
  Connect, Disconnect, Copy command, Rename, Forget, Disconnect all, and Forget all actions.
- A connection panel on the header chip showing the current headset, attached devices to choose
  from when several are plugged in, saved wireless Quests with one-click connect, and the wireless
  actions; the refresh control is a small icon beside it.
- A configurable default app ID tag (`.mr`, `.dev`, `.test`, `.qa`, or custom) used for every new
  suggestion.
- Uninstall-and-reinstall recovery when the Quest rejects an APK because of a signing or version
  conflict, with readable explanations of `INSTALL_FAILED_*` codes.

### Fixed

- An APK-only install (for example a finished folder without OBBs, or a patch sideload) no
  longer deletes the OBB files that already exist on the Quest for that package.
- Retrying a failed OBB transfer no longer removes the other OBBs of the same game, and a
  transfer that failed before the APK was installed now reruns the complete install instead of
  pushing OBBs for an app that is not there yet.
- Stale `.qar-new-*` staging files left by an interrupted transfer are now found and removed
  (`ls` hides dotfiles on the headset without `-a`).
- Renaming `com.example.game` no longer corrupts neighbouring identifiers such as
  `com.example.gamepad` or `Lcom/example/gamepad/…;`; references are matched as whole tokens,
  and the Inspector preview uses exactly the same rule as the rewrite.
- Version code, version name, and SDK levels are read from `apktool.yml` when recent Apktool
  releases strip them from the decoded manifest, so the Dashboard, Library version comparison,
  and `release.manifest` no longer report an empty or default version.
- Folders the app creates next to the signing identity (`app-icons`, `imported-identities`)
  no longer make the app believe the signing identity is incomplete before the first key exists.
- The automatic device poll no longer overwrites the build or install result shown on the
  Dashboard, and a symlinked APK no longer leaves the Dashboard stuck in "analyzing".
- Choosing another source while a build or install is running is refused instead of mixing the
  finished result into the new selection; the "Install built game" action always installs the
  package ID that was actually built.
- Unexpected exceptions in the device poll, update check, tool repair, Library archive, and bulk
  build/install workers no longer leave the app permanently busy; bulk install stops cleanly
  when the headset disconnects mid-queue.
- Direct Quest updates no longer show a misleading "local folder was kept" warning.
- `release.manifest` records the final output folder name instead of the hidden staging name,
  finished output folders are created with normal permissions, and tool errors show the real
  Java diagnostic instead of the last stack-trace line.
- Upper-case `.APK`/`.OBB` extensions are recognised, and a phone connected next to the headset
  no longer blocks the Quest from being selected.
- Sidebar icons sit on the text baseline, and the hover highlight no longer flickers between rows.
- Dashboard, Settings, and Inspector pages scroll a fixed distance per wheel notch with no kinetic
  overshoot; touchpads scroll by their pixel delta.

### Changed

- Dashboard: Clear, Open, and Copy actions for the source, save location, package ID, and error
  message; an elapsed-time counter during operations; debounced package-ID validation; tag
  buttons disabled during direct Quest updates; and the drop zone disabled while busy.
- Library: selecting an app no longer rebuilds the list (and no longer scrolls to the top),
  Up/Down keys move the selection, and the live-view choice survives routine device polls.
- Bulk queue: per-entry Open and Copy-error actions, a "Remove finished" action, a clear note
  when unbuilt entries would install under their original package ID, and queue-level
  refreshes only on status changes instead of every progress tick.
- Logs window follows new lines unless scrolled away, remembers its size, closes with `Esc`, and
  UI refreshes for log bursts are coalesced (1–3 ms per line saved during builds).
- Install progress shows transfer speed and time remaining for large OBB pushes and a heartbeat
  during the APK install; remote OBB listing, hashing, and cleanup use far fewer ADB round trips.
- Startup hashes each bundled tool once instead of two or three times and defers the network
  stack until an update check or tool repair actually runs; the log tail is read from the end of
  the file.
- Package-reference scanning walks the decoded tree with one `stat` per file and larger chunks,
  the Inspector hashes MD5/SHA-1/SHA-256 in parallel and shares the Apktool framework cache, and
  the signer's own verification report is trusted instead of starting a second JVM.
- Preflight checks free space on the app cache drive as well as the output drive, and reports a
  read-only save location before the build starts.
- Shared UI components (panels, captions, switches, scroll bars, progress bars) replace ad-hoc
  copies, pages use one margin, panels size to their content, and tooltips explain ambiguous
  buttons; `Enter` activates dialog buttons.
- Linux packages omit Qt PDF, the virtual keyboard, and unused image-format plugins.

## [1.4.5] - 2026-08-21

### Added

- A connected-headset Library view that lists user-installed Quest apps and starts guided APK or
  complete-folder updates from the selected installed package.
- Portable `.qarlib` archives for exporting or importing one saved signing identity or the full
  vault, including profile details, private signing keys, key metadata, cached icons, and integrity
  hashes.
- Selectable vault entries with copy-one, copy-all, export, open-key-folder, and safe remove
  actions. Removing an entry forgets its Library mapping while retaining its key files for recovery.
- Cached Quest-visible app labels and launcher icons for analyzed builds. Original and renamed
  packages with the same display name reuse one local icon instead of storing duplicates.
- Recovery copies and last-known-good backups for damaged Library and settings JSON files.

### Changed

- The Library now opens on the live connected-headset inventory. Its secondary key-vault view
  shows saved original-to-renamed identities and key health, while update actions and
  installed-version checks remain tied only to current headset state.
- OBB filenames retain numeric version tags and Unreal-style tags such as
  `pakchunk0-Android_ASTC` while only the Android package portion is renamed. Safe asset OBBs in
  a proven game/package folder keep their original names.
- Exact APK selections perform a second safe OBB match after analysis learns the real package ID,
  so matching expansion files are found without claiming neighboring games.
- Release runtimes, Python build inputs, and GitHub Actions are pinned and verified before use.
- Library rows and signing-key health are cached until their backing state changes, and the UI now
  virtualizes large saved/live app lists instead of constructing every row at once.
- Connected-headset inventory reads package version codes in one package-manager call on current
  firmware, with a bounded compatibility fallback for older Android package managers.
- Decoded APK reference scans use bounded-memory streaming for assets and native files, while OBB
  retries reuse local hashes only while the file size and modification time remain unchanged.
- Linux packages omit unused Qt translations and development-only QML tooling after frozen and
  AppImage launch verification.

### Fixed

- Reject mismatched, unsupported, or colliding OBB names before build output can be overwritten.
- Clean up obsolete numeric and pakchunk OBB files only after an update is fully verified, while
  preserving unrelated files in the Quest package directory.
- Restore or retain uniquely named OBB backups when verification fails after APK installation.
- Prevent stale device-inventory workers from wedging the Library after switching headsets.
- Apply shared bundled-CA handling to update checks and tool repair across packaged platforms.
- Bound external build, inspection, signing, and ADB commands with safe timeout/process cleanup.
- Clear every pending Library/direct-update state when the Dashboard is reset.
- Fall back correctly when an older Android package manager reports an unsupported version-list
  option with a successful exit code, and tolerate source files disappearing during preflight.
- Discard corrupt cached launcher icons so a later analysis can replace them cleanly.

## [1.4.4] - 2026-08-08

### Added

- An automatic game Library that records each original-to-renamed identity after a successful
  build or verified install, including its exact signing key and installed OBB set.
- Guided Library updates that restore the saved app ID and signing identity after confirming the
  selected APK belongs to the same original package and signer.
- An optional default signing-key backup folder with automatic backup and a confirmation showing
  the exact destination. Library key storage remains automatic and independent.
- A three-choice output collision prompt: cancel, move the existing output to Trash and replace
  it, or build into the next available numbered folder such as ` - Renamed (2)`.
- MIT-licensed Bootstrap Icons for clearer sidebar navigation.

### Changed

- Quest OBB updates now compare existing data, skip identical files, reuse identical versioned
  OBBs without uploading them again, stage replacements transactionally, and remove obsolete
  managed/versioned OBBs only after APK and OBB verification succeeds.
- Simplified the Library into a readable original/renamed identity list and one selected-game
  update panel instead of exposing key hashes and storage paths as primary UI.
- Expanded navigation click targets into the visual gaps without changing button or highlight
  sizes.

### Fixed

- Enabling the older-firmware patch no longer replaces the Dashboard's current readiness or error
  message. Compatibility remains visible in the source card and toggle description.
- Existing non-empty output folders no longer leave the build button permanently blocked.
- Library updates reuse their pinned signing key instead of silently falling back to a newly
  generated identity, and reject missing, changed, or mismatched keys before building.
- Failed APK installation restores the prior OBB set when activation had already begun.

## [1.4.2] - 2026-08-08

### Added

- A compact source-card OFP compatibility indicator with an explanatory hover
  tooltip.
- More informative operation progress with the active target, exact percentage,
  OFP stage, and byte-level APK/OBB copy details.

### Changed

- The older-firmware patch preference can now be enabled before or after source
  selection and stays enabled across games. It is applied only when analysis
  confirms the compatible ARM64 loader is present; other APKs are left unpatched.
- Moved the rename arrows upward toward the center of the application icon.

## [1.4.0] - 2026-08-01

### Added

- A complete Qt Quick dashboard with dedicated Bulk, APK Inspector, Settings,
  and standalone Logs windows.
- Full APK package rewriting, rebuilding, persistent signing, verification,
  OBB renaming, manifest generation, atomic publishing, and detailed reports.
- APK inspection with signer lineage, signature schemes, certificates, SDK and
  ABI details, hashes, components, permissions, features, and rename-impact
  previews.
- Sequential bulk build and install queues with per-game results and safe
  cancellation boundaries.
- Portable Linux tarball and AppImage packages, a Windows portable ZIP and
  per-user installer, and native Apple Silicon and Intel macOS DMGs.

### Changed

- Replaced the legacy Tk interface and tightly coupled implementation with a
  typed, testable domain/service/infrastructure architecture and a responsive
  QML interface.
- Unified all file browsing behind native, Qt, and desktop-helper fallback
  layers so broken desktop portals do not silently disable Browse buttons.
- Moved long-running analysis, building, installation, device discovery,
  updates, and tool repair off the interface thread.
- Reduced bundled dependencies by replacing the vendored drag-and-drop toolkit
  with Qt's built-in support and downloading pinned Android tools at build time.

### Compatibility

- Reuses the released app's data directory, signing identity, Windows installer
  identity, macOS bundle identity, and GitHub update channel.
- Migrates an existing legacy signing key into the new PKCS#12 store after
  validating it with Java `keytool`; the original key files are preserved.
- Preserves the existing package/OBB workflow, older-firmware patch, source
  replacement, verified post-install cleanup, crash recovery, and safe partial
  cleanup behavior.

### Safety

- Original inputs remain untouched unless source replacement is explicitly
  enabled, and replacement uses a verified staging folder with rollback.
- Post-install cleanup only runs after APK and every OBB have been verified on
  the Quest.
- Tool downloads and the optional compatibility asset are pinned and
  SHA-256-verified before atomic activation.

## [1.3.2] - 2026-07-31

### Changed

- Relied on GitHub's displayed release-asset SHA-256 digests instead of
  publishing redundant platform checksum files.
- Added packaged Linux launch checks on Ubuntu 26.04, Debian 12, and current
  Fedora before a tagged build can be published.

### Fixed

- Made Linux folder/APK pickers desktop-aware, normalized missing starting
  directories, and fall back through other native helpers and bundled Tk when
  a dialog backend fails instead of silently doing nothing.
- Corrected frozen Linux app-launcher entries to target the packaged executable.
- Added distinct Linux ADB guidance when USB access is blocked by missing udev
  permissions.
- Prevented legacy `v1.8` and `v1.9` tags from appearing as updates to the
  renumbered v1.3 release, and included published prereleases in update checks.

## [1.3.0] - 2026-07-31

### Added

- Opt-in older-firmware compatibility for APKs containing the ARM64
  `libovrplatformloader.so`, with automatic availability detection, pinned
  upstream provenance, checksum verification, and build-report auditing.

### Changed

- Simplified feature requests by removing the app-version question and adding
  an `All` operating-system choice.
- Corrected the project version sequence: the earlier 1.7, 1.8, and 1.9
  development milestones map to 1.0, 1.1, and 1.2 respectively.

## [1.2.0] - 2026-07-29

### Added

- Background APK analysis for labels, SDK levels, OpenGL ES, ABIs, locales,
  components, permissions, features, and MD5/SHA-1/SHA-256 hashes.
- V1/V2/V3 signature verification, certificate details, and a reviewable
  known-signer registry.
- Full technical package-reference previews with preserved asset/native-code
  warnings.
- Human-readable and JSON package-change reports with source/output signing
  provenance in every completed bundle.
- Quick package-ID suffix/tag presets and already-renamed warnings.
- GitHub release/tag update checks with a dismissible update banner.
- A rotating persistent debug log with open and export actions.

### Changed

- Redesigned the main window into a responsive, guided three-step workspace.
- Added a live workflow rail, per-step status badges, automatic-check pills,
  and clearer locked/ready states.
- Improved narrow-window card stacking and removed clipped helper text.
- Polished the APK inspector, bulk queue, options view, and action labels into
  one consistent visual system.
- Replaced the README screenshots and added a concise feature overview.
- Kept scrolling available without showing a permanent scrollbar and
  simplified main-window actions.
- Rewrote the README around the beginner workflow and shorter reference
  sections.
- Reduced release size with a `jlink` Java runtime built from three required
  root modules.
- Package only the native tkdnd backend required by each release target.
- Fall back to the standard folder picker if the native drag-and-drop backend
  cannot load, instead of preventing the app from launching.

## [1.1.0] - 2026-07-29

### Added

- Native macOS application and DMG packaging for Apple Silicon and Intel Macs.
- Bundled macOS Java, `keytool`, and Android Platform-Tools runtimes.
- macOS Finder pickers, Finder Trash support, and user Applications install.
- GitHub Actions builds for both macOS architectures, with optional Developer
  ID signing and notarization.
- Self-contained Linux x86_64 package with bundled Java, ADB, and a per-user
  app-launcher installer.
- GitHub issue forms for installation help and release-package problems.
- Opt-in source-folder replacement using a completed sibling staging build.
- Rollback to the original folder if replacement activation fails.
- Recoverable original-folder cleanup through Trash after replacement.
- Opt-in local-folder cleanup only after APK, OBB, and package verification
  succeeds on the Quest.
- Bulk folder picker with direct-parent scanning and multi-folder drag-and-drop.
- Multi-select APK picker for adding several games to a bulk queue at once.
- Configurable package suffix preview, defaulting to `a`.
- Sequential bulk rename and bulk install queues.
- Per-folder success/failure overview after every bulk operation.
- Aggregate local and Quest storage warnings for bulk queues.
- Persistent toggle for enabling or disabling automatic signing-key backup
  questions.
- Automatic readiness checks with a suggested separate package ID.

### Changed

- Simplified the main workflow to short, next-step guidance with no manual
  preflight action.
- Reworked advanced switches into a compact two-column layout.
- Moved Bulk tools into the always-visible main footer.
- Added a prominent AI-assistance and beta-safety disclosure to the README.

### Safety

- Bulk source replacement refuses to omit detected OBB files.
- Post-install cleanup only accepts app-created folders containing
  `RENAMED-BUNDLE.txt`.
- Failed installs and verification failures always preserve local folders.
- Nested and duplicate bulk selections are rejected.
- Bulk cancellation stops at the existing safe stage boundaries.

## [1.0.0] - 2026-07-28

### Added

- Complete three-step package rename, rebuild, signing, and install workflow.
- Folder selection and native folder drag-and-drop.
- Matching OBB rename and `release.manifest` generation.
- Connected Quest status card with headset model and available storage.
- Preflight checks for package rules, tools, input readability, output safety,
  local space, and Quest space.
- Weighted build progress and byte-based OBB transfer progress.
- Persistent local signing identity and backup reminders.
- Package-conflict warning and post-install verification.
- Retry of only failed OBB transfers.
- Safe cancellation with optional partial-output cleanup.
- Managed-output cleanup through Trash or the Windows Recycle Bin.
- Linux application-menu and Windows Start Menu shortcuts.
- Windows portable build and per-user Inno Setup installer.
- Automated Windows release artifact workflow.
- MIT License for the project source.

### Safety

- Source APK, OBB, and manifest files are never modified.
- Package replacement is limited to decoded technical Android files.
- Game-facing text and assets are intentionally excluded.
- Cleanup refuses folders without the managed-output marker.

[1.4.5]: ../../releases/tag/v1.4.5
[1.4.4]: ../../releases/tag/v1.4.4
[1.4.2]: ../../releases/tag/v1.4.2
[1.4.0]: ../../releases/tag/v1.4.0
[1.3.2]: ../../releases/tag/v1.3.2-beta.1
[1.3.0]: ../../releases/tag/v1.3.0-beta.1
[1.2.0]: ../../releases/tag/v1.9.0-beta.1
[1.1.0]: ../../releases/tag/v1.8.0-beta.1
