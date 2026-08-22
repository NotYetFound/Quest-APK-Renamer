# Signing-key vault and connected-headset updates

The Library has two deliberately separate views. It opens on a live inventory read from an
authorized Quest; the secondary vault view manages the signing identities recorded by previous
renamed builds. It is not a required step in the normal Dashboard workflow.

## Normal behavior

1. A successful renamed build records the original package ID, renamed package ID, source
   version, output location, selected patches, and the exact PKCS#12/JSON signing identity used.
2. A verified install may add device/OBB bookkeeping to an existing managed identity, but this
   stored history is never presented as the Quest's current state.
3. Selecting a later source with one unambiguous vault match restores the renamed ID and key.
4. The default live-headset view reads current third-party package/version data from the connected
   device. Its update actions pin that actual package before the source is analyzed. A different
   package ID or recognized source signer is rejected instead of being treated as an update.
5. Installing an already-present package offers only **Update** and **Cancel**. A separate copy
   must first be built with a different app ID.

The durable files are deliberately simple and portable:

```text
<app data>/library.json
<app data>/signing/quest-renamer.p12
<app data>/signing/identity.json
<app data>/signing/lineage-keys/*.p12
<app data>/signing/lineage-keys/*.json
<app data>/signing/app-icons/*
```

The JSON metadata includes signing passwords so builds can reuse a key without prompts. These
files are private credentials and should be backed up and shared only as a complete private key
backup.

## Vault portability

The vault can copy one or every identity as human-readable clipboard text. This includes the saved
profile and readable key metadata, so clipboard contents must be treated as private credentials.

One identity or the complete vault can also be exported as a `.qarlib` archive. An archive contains
the full saved profile, PKCS#12 signing key, JSON key metadata, and cached icon for each selected
identity. Each file has a recorded size and SHA-256 hash. Import validates the archive structure,
paths, IDs, file limits, and hashes before copying private files into a new local identity folder
and merging the profiles into the vault. Imported key files use private filesystem permissions.

Removing a vault entry removes its automatic matching record but deliberately keeps its key files
on disk for recovery. Use **Open key folder** before removal if you want to locate or back them up.

## Signing invariants

- An existing Library identity is never silently assigned a newly generated key.
- A missing, incomplete, or changed saved key blocks the update before building.
- The build request pins the exact saved key and metadata paths instead of merely asking the
  general signing store for a key.
- A saved renamed identity cannot be reused with APK signing disabled.
- A lower numeric version code is blocked only when the live headset inventory confirms a newer
  installed version; stale local history does not block a build.

## OBB synchronization

OBBs are synchronized as a verified set rather than pushed blindly:

1. Inventory the target package's Quest OBB directory.
2. Hash same-sized candidates when the Quest provides `sha256sum` or Toybox.
3. Skip a same-name, identical OBB.
4. Rename an identical package-matching OBB already on the Quest instead of uploading it again.
5. Upload changed data under a temporary `.qar-new-*` name and verify its size.
6. Stop the package, preserve replaced files as `.qar-old-*`, and activate the prepared set.
7. Install and verify the APK, then verify every expected OBB.
8. Only after success, remove transaction backups and obsolete package-matching
   `main.*`/`patch.*` OBBs, including numeric and Unreal `pakchunk` tags.

The saved managed-OBB list also permits cleanup when a later update removes or renames a preserved
asset OBB. Unrecognized files are preserved. If installation or post-install verification fails,
the prior OBB set is restored or retained under unique recovery names.

## Minimal interface

The Dashboard remains the primary workspace. The Library page provides:

- a default live-headset inventory of current third-party apps and versions;
- one readable key-vault row per automatically recorded original-to-renamed identity;
- Quest-visible names, original/renamed IDs, key health, and cached launcher icons;
- copy, individual/full export, import, and safe removal tools in the secondary vault view;
- APK/folder update actions only for an app selected from that live inventory; and
- a shortcut to each selected identity's private key folder when deeper debugging is needed.

App icons are cached by normalized display name, so original and renamed IDs can share one image.
Unknown live apps use a neutral fallback rather than pulling every installed APK from the Quest.
