# Changelog

All notable changes to Quest APK Renamer are recorded here.

## Unreleased

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

[1.4.4]: ../../releases/tag/v1.4.4
[1.4.2]: ../../releases/tag/v1.4.2
[1.4.0]: ../../releases/tag/v1.4.0
[1.3.2]: ../../releases/tag/v1.3.2-beta.1
[1.3.0]: ../../releases/tag/v1.3.0-beta.1
[1.2.0]: ../../releases/tag/v1.9.0-beta.1
[1.1.0]: ../../releases/tag/v1.8.0-beta.1
