# Changelog

All notable changes to Quest APK Renamer are recorded here.

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
[1.8.0]: ../../releases/tag/v1.8.0
