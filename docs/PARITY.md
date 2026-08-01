# Original feature parity

This checklist keeps the v1 architecture focused on proven workflows from the legacy application
without copying its single-file UI architecture.

## Available in v1.4

- Folder selection, exact single-APK drag-and-drop, native dialogs, and drag-and-drop.
- Automatic APK metadata analysis and package-ID suggestions.
- Full APK decode, package rewrite, rebuild, persistent-key signing, and signature verification.
- OBB directory and filename rewriting plus `release.manifest`, readable and JSON change reports,
  and the original `RENAMED-BUNDLE.txt` marker.
- Automatic preflight, host/Quest space checks, safe cancellation, and partial-build handling.
- Verified APK-and-OBB installation, existing-package confirmation, and failed-OBB retry.
- Rollback-protected source replacement and verified post-install local cleanup.
- Signing-key backup/restore and optional older-firmware loader patch.
- CN/O-only signer recognition, cert-embedded source lineage, cached lineage identities, and
  lineage-aware key backups.
- `.mr`, `.dev`, `.test`, and `.qa` package-ID tag presets.
- Multi-APK/folder bulk queue, parent scanning, suffix previews, sequential build/install,
  failure isolation, cancellation, and final overview.
- Detailed APK Inspector with full metadata, hashes, schemes/certificates, signer identity,
  permissions/features, package-reference rename preview, safe cancellation, and JSON export.
- Pinned Apktool and APK-signer status, checksum verification, cancellable automatic repair,
  atomic replacement, and immediate activation without restarting the app.
- Quiet automatic and explicit manual update checks, preview-aware version ordering, dismissible
  release banners, legacy tag ordering, and the normal release channel.
- Persistent 5 MB rotating raw diagnostic log with UTC timestamps, complete external-tool output,
  readable operation headings, open/export actions, and secret-value redaction.
- Report-verified old-output cleanup with exact-target confirmation and Trash-only removal.
- Crash-persistent staging recovery with open, keep, and guarded removal choices.
- One-click support summary, current-session log view, contextual failure log/report actions,
  visible keyboard focus, page shortcuts, and safe default focus in destructive dialogs.

## Remaining release validation

1. Final Windows and macOS builds on their native CI runners and real-machine validation.
2. Wider distro testing for the portable tarball and AppImage.
3. A DEB package only if users still need one after AppImage testing.
