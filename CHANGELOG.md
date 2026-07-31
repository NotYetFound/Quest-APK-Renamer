# Changelog

All notable changes to Quest APK Renamer are recorded here.

## Unreleased

### Added

- Opt-in older-firmware compatibility for APKs containing the ARM64
  `libovrplatformloader.so`, with automatic availability detection, pinned
  upstream provenance, checksum verification, and build-report auditing.

## [1.9.0] - 2026-07-29

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

## [1.8.0] - 2026-07-29

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

## [1.7.0] - 2026-07-28

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

[1.7.0]: ../../releases/tag/v1.7.0
[1.8.0]: ../../releases/tag/v1.8.0-beta.1
[1.9.0]: ../../releases/tag/v1.9.0-beta.1
