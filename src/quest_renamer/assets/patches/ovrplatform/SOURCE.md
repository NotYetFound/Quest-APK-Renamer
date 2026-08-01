# Older firmware compatibility loader

The optional `libovrplatformloader.so` replacement comes from
[veygax/eventhorizon](https://github.com/veygax/eventhorizon), revision
`9ffe7009ae10601bf72ed57455d31ef051495f84`.

The expected SHA-256 is
`1f6d43e6b7b82960efdaf6596953272c32022316375ddca1eddc56e15b026ca2`.
Quest APK Renamer verifies this value before and after replacement. The verified-components
repair action downloads the pinned upstream asset into the app data directory. Release packaging
may bundle the same verified file, and source builds may override its location with
`QAR_OLDER_FIRMWARE_PATCH`.
