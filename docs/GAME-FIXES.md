# Game-specific fixes

Some games keep their package ID in places the generic package rewrite does not reach, such as
data inside an OBB. A *game fix* repairs those places for one game.

## What a game fix is

- Automatic: there is no UI toggle.
- Selected by the exact, case-sensitive SOURCE package ID of the build
  (`fixes_for(source_package)` in `infrastructure/game_fixes/__init__.py`).
- Run only when the package ID changes. Patch-only builds that keep the package ID skip them.
- Never run for any other package: no parsing, no rewriting, no new failure modes.

Each applied change appears in the build report under `game_fixes` (JSON) and
"GAME-SPECIFIC FIXES" (text), prefixed with the fix's `fix_id`.

## Fail closed

- Inside a matching game, a layout the fix does not recognise raises `GameFixError`
  (a `ValueError`), which fails the build with that message; nothing is published or
  replaced. It is never silently skipped.
- If the files a fix targets are simply absent (or already name the new package), the fix is a
  no-op, not an error.

## Adding a fix

1. Add a module in `infrastructure/game_fixes/` with a class implementing the `GameFix`
   protocol from `base.py`: `fix_id` (kebab-case), `title`, `source_packages`,
   `apply_to_decoded_apk(context, decoded)` and `apply_to_obb(context, obb_path)`. Explain in
   the module docstring why the game needs it.
2. Add one instance to `GAME_FIXES` in `game_fixes/__init__.py`.
3. Add tests (the registry tests in `tests/test_game_fixes.py` cover id and package rules).
4. Add a `CHANGELOG.md` entry naming the game.

## Reusable toolkit

- `infrastructure/addressables_catalog.py`: reads Unity Addressables v2 binary catalogs and
  repoints a shared path segment by appending a replacement string.
- `infrastructure/zip_stored_entry.py`: rewrites one STORED, non-ZIP64 entry of a ZIP in place
  (including OBBs), patches the central directory, verifies the result and honours
  cancellation.

Both are package-agnostic and take the old and new strings as parameters.
