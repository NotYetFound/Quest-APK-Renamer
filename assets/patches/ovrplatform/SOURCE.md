# Older firmware compatibility loader

`libovrplatformloader.so` is bundled for the optional **Older firmware
compatibility** build setting.

- Upstream project: [veygax/eventhorizon](https://github.com/veygax/eventhorizon)
- Upstream revision: `9ffe7009ae10601bf72ed57455d31ef051495f84`
- Upstream path: `app/src/main/assets/ovrplatform/libovrplatformloader.so`
- SHA-256: `1f6d43e6b7b82960efdaf6596953272c32022316375ddca1eddc56e15b026ca2`
- Architecture: Android ARM64 (`arm64-v8a`)

Quest APK Renamer verifies this checksum before and after every replacement.
The setting is off by default and is only offered when the source APK already
contains `lib/arm64-v8a/libovrplatformloader.so`.

See `LICENSE` in this directory and the repository's
`THIRD_PARTY_NOTICES.md`.
