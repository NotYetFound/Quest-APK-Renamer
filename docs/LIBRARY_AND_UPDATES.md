# Library and automatic game updates

The Library is an optional view over state the app records automatically. It is not a required
step in the normal Dashboard workflow.

## Normal behavior

1. A successful renamed build records the original package ID, renamed package ID, source
   version, output location, selected patches, and the exact PKCS#12/JSON signing identity used.
2. A verified Quest install adds the installed version, device serial, and managed OBB names.
3. Selecting a later source with one unambiguous Library match restores the renamed ID and key.
4. The Library's **Choose update** action pins a specific profile before the source is analyzed.
   A different package ID or recognized source signer is rejected instead of being treated as an
   update.
5. Installing an already-present package offers only **Update** and **Cancel**. A separate copy
   must first be built with a different app ID.

The durable files are deliberately simple and portable:

```text
<app data>/library.json
<app data>/signing/quest-renamer.p12
<app data>/signing/identity.json
<app data>/signing/lineage-keys/*.p12
<app data>/signing/lineage-keys/*.json
```

The JSON metadata includes signing passwords so builds can reuse a key without prompts. These
files are private credentials and should be backed up and shared only as a complete private key
backup.

## Signing invariants

- An existing Library identity is never silently assigned a newly generated key.
- A missing, incomplete, or changed saved key blocks the update before building.
- The build request pins the exact saved key and metadata paths instead of merely asking the
  general signing store for a key.
- An installed Library game cannot be updated with APK signing disabled.
- Selecting a lower numeric version code is blocked; equal versions remain useful for developer
  rebuilds.

## OBB synchronization

OBBs are synchronized as a verified set rather than pushed blindly:

1. Inventory the target package's Quest OBB directory.
2. Hash same-sized candidates when the Quest provides `sha256sum` or Toybox.
3. Skip a same-name, identical OBB.
4. Rename an identical versioned OBB already on the Quest instead of uploading it again.
5. Upload changed data under a temporary `.qar-new-*` name and verify its size.
6. Stop the package, preserve replaced files as `.qar-old-*`, and activate the prepared set.
7. Install and verify the APK, then verify every expected OBB.
8. Only after success, remove transaction backups and obsolete `main.*`/`patch.*` OBBs.

The Library's previously managed OBB list also permits cleanup when a later update removes or
renames a non-versioned OBB. Unrecognized files are preserved. If APK installation fails, the
prior OBB set is restored.

## Minimal interface

The Dashboard remains the primary workspace. The Library page provides only:

- one readable row per automatically recorded original-to-renamed identity;
- installed/built state, version, and key readiness at a glance;
- one selected-game panel explaining that its saved app ID and key will be reused;
- separate actions for choosing a newer APK or complete game folder; and
- shortcuts to the private key and Library data folders when deeper debugging is needed.

Future device refresh work can add live `Up to date`, `Update available`, and `Not installed`
states without changing this storage format or making Library management mandatory.
