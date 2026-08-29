import tempfile
import unittest
from pathlib import Path

from quest_renamer.domain.operations import CancellationToken
from quest_renamer.infrastructure.package_rewriter import replace_package_references
from quest_renamer.infrastructure.reference_scanner import (
    find_jni_libraries,
    jni_export_prefix,
)


class PackageRewriterTests(unittest.TestCase):
    def test_only_identity_references_in_technical_files_are_changed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            decoded = Path(temporary)
            manifest = decoded / "AndroidManifest.xml"
            smali = decoded / "smali" / "com" / "example" / "Main.smali"
            resource = decoded / "res" / "xml" / "provider.xml"
            asset = decoded / "assets" / "config.json"
            for path in (smali, resource, asset):
                path.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text('package="com.example.game"', encoding="utf-8")
            smali.write_text(
                'Lcom/example/game/Main;\nconst-string v0, "com.example.game"\n',
                encoding="utf-8",
            )
            resource.write_text("com.example.game.provider", encoding="utf-8")
            asset.write_text('"com.example.game"', encoding="utf-8")

            result = replace_package_references(
                decoded,
                "com.example.game",
                "com.dev.example.game",
                token=CancellationToken(),
            )

            self.assertEqual(result.changed_files, 3)
            self.assertEqual(result.changed_occurrences, 3)
            self.assertEqual(result.namespace_references, 1)
            self.assertIn("com.dev.example.game", manifest.read_text(encoding="utf-8"))
            text = smali.read_text(encoding="utf-8")
            self.assertIn("Lcom/example/game/Main;", text)
            self.assertIn('"com.dev.example.game"', text)
            self.assertEqual(
                resource.read_text(encoding="utf-8"), "com.dev.example.game.provider"
            )
            self.assertEqual(asset.read_text(encoding="utf-8"), '"com.example.game"')
            self.assertEqual(result.preserved_files, ("assets/config.json",))

    def test_java_class_names_survive_so_native_code_still_binds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            decoded = Path(temporary)
            layout = decoded / "res" / "layout" / "main.xml"
            smali = decoded / "smali" / "Main.smali"
            for path in (layout, smali):
                path.parent.mkdir(parents=True, exist_ok=True)
            layout.write_text(
                '<cn.vr4p.player.MainUI.ThumbnailView xmlns:ns1="http://schemas.android.com'
                '/apk/res/cn.vr4p.player" />',
                encoding="utf-8",
            )
            smali.write_text(
                'const-string v0, "cn.vr4p.player.action.BRING_SELF_TO_FRONT"\n'
                'const-string v1, "cn.vr4p.player.Oof.OofToken"\n'
                'const-string v2, "cn.vr4p.player.R"\n'
                'const-string v3, "cn.vr4p.player.permission.C2D_MESSAGE"\n'
                'const-string v4, "cn.vr4p.player.fileprovider"\n'
                "invoke-static {}, Lcn/vr4p/player/Main4XActivity;->init()V\n",
                encoding="utf-8",
            )

            result = replace_package_references(
                decoded, "cn.vr4p.player", "cn.dev.vr4p.player", token=CancellationToken()
            )

            self.assertEqual(result.changed_occurrences, 4)
            self.assertEqual(result.namespace_references, 4)
            self.assertEqual(
                layout.read_text(encoding="utf-8"),
                '<cn.vr4p.player.MainUI.ThumbnailView xmlns:ns1="http://schemas.android.com'
                '/apk/res/cn.dev.vr4p.player" />',
            )
            text = smali.read_text(encoding="utf-8")
            self.assertIn('"cn.dev.vr4p.player.action.BRING_SELF_TO_FRONT"', text)
            self.assertIn('"cn.vr4p.player.Oof.OofToken"', text)
            self.assertIn('"cn.vr4p.player.R"', text)
            self.assertIn('"cn.dev.vr4p.player.permission.C2D_MESSAGE"', text)
            self.assertIn('"cn.dev.vr4p.player.fileprovider"', text)
            self.assertIn("Lcn/vr4p/player/Main4XActivity;", text)

    def test_relative_manifest_components_are_qualified_with_the_old_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            decoded = Path(temporary)
            manifest = decoded / "AndroidManifest.xml"
            manifest.write_text(
                """<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.example.game" android:sharedUserId="com.example.game.shared">
    <permission android:name="com.example.game.permission.PLAY"/>
    <application android:name=".App" android:backupAgent="Agent">
        <activity android:name=".ui.Main" android:taskAffinity="com.example.game"/>
        <activity-alias android:name="Alias" android:targetActivity=".ui.Main"/>
        <service android:name="com.example.game.Sync"/>
        <provider android:name="androidx.core.content.FileProvider"
            android:authorities="com.example.game.fileprovider;com.example.game.files"/>
        <meta-data android:name="com.example.game.key" android:value="x"/>
        <receiver android:name="Receiver"><intent-filter>
            <action android:name="com.example.game.ACTION_WAKE"/>
        </intent-filter></receiver>
    </application>
</manifest>
""",
                encoding="utf-8",
            )

            result = replace_package_references(
                decoded, "com.example.game", "com.example.game.mr", token=CancellationToken()
            )

            text = manifest.read_text(encoding="utf-8")
            self.assertEqual(result.qualified_components, 6)
            self.assertIn('package="com.example.game.mr"', text)
            self.assertIn('android:sharedUserId="com.example.game.mr.shared"', text)
            self.assertIn('android:name="com.example.game.mr.permission.PLAY"', text)
            self.assertIn('android:name="com.example.game.App"', text)
            self.assertIn('android:backupAgent="com.example.game.Agent"', text)
            self.assertIn('android:name="com.example.game.ui.Main"', text)
            self.assertIn('android:taskAffinity="com.example.game.mr"', text)
            self.assertIn('android:name="com.example.game.Alias"', text)
            self.assertIn('android:targetActivity="com.example.game.ui.Main"', text)
            self.assertIn('android:name="com.example.game.Sync"', text)
            self.assertIn('android:name="androidx.core.content.FileProvider"', text)
            self.assertIn(
                'android:authorities="com.example.game.mr.fileprovider;'
                'com.example.game.mr.files"',
                text,
            )
            self.assertIn('android:name="com.example.game.mr.key"', text)
            self.assertIn('android:name="com.example.game.Receiver"', text)
            self.assertIn('android:name="com.example.game.mr.ACTION_WAKE"', text)

    def test_jni_libraries_are_detected_and_block_legacy_namespace_renames(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            decoded = Path(temporary)
            lib = decoded / "lib" / "arm64-v8a" / "libgame.so"
            other = decoded / "lib" / "arm64-v8a" / "libcodec.so"
            smali = decoded / "smali" / "Main.smali"
            for path in (lib, other, smali):
                path.parent.mkdir(parents=True, exist_ok=True)
            lib.write_bytes(b"\x00Java_com_my_1game_app_Main_nativeInit\x00")
            other.write_bytes(b"\x00Java_org_other_Lib_init\x00")
            smali.write_text("Lcom/my_game/app/Main;", encoding="utf-8")
            (decoded / "AndroidManifest.xml").write_text(
                'package="com.my_game.app"', encoding="utf-8"
            )

            self.assertEqual(jni_export_prefix("com.my_game.app"), b"Java_com_my_1game_app_")
            self.assertEqual(
                find_jni_libraries(decoded, "com.my_game.app", CancellationToken()),
                ("lib/arm64-v8a/libgame.so",),
            )
            with self.assertRaisesRegex(ValueError, "native code binds"):
                replace_package_references(
                    decoded,
                    "com.my_game.app",
                    "com.dev.my_game.app",
                    token=CancellationToken(),
                    rename_java_packages=True,
                )
            self.assertIn("Lcom/my_game/app/Main;", smali.read_text(encoding="utf-8"))

            result = replace_package_references(
                decoded, "com.my_game.app", "com.dev.my_game.app", token=CancellationToken()
            )

            self.assertEqual(result.jni_libraries, ("lib/arm64-v8a/libgame.so",))
            self.assertFalse(result.java_packages_renamed)
            self.assertIn("Lcom/my_game/app/Main;", smali.read_text(encoding="utf-8"))

    def test_legacy_mode_renames_java_packages_when_no_native_code_binds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            decoded = Path(temporary)
            smali = decoded / "smali" / "Main.smali"
            smali.parent.mkdir(parents=True)
            smali.write_text(
                'Lcom/example/game/Main;\nconst-string v0, "com.example.game.ui.Main"\n',
                encoding="utf-8",
            )
            (decoded / "AndroidManifest.xml").write_text(
                'package="com.example.game"', encoding="utf-8"
            )

            result = replace_package_references(
                decoded,
                "com.example.game",
                "com.example.game.mr",
                token=CancellationToken(),
                rename_java_packages=True,
            )

            self.assertTrue(result.java_packages_renamed)
            self.assertEqual(result.changed_occurrences, 3)
            self.assertEqual(result.namespace_references, 0)
            text = smali.read_text(encoding="utf-8")
            self.assertIn("Lcom/example/game/mr/Main;", text)
            self.assertIn('"com.example.game.mr.ui.Main"', text)

    def test_component_classes_of_any_shape_and_foreign_packages_are_protected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            decoded = Path(temporary)
            smali_dir = decoded / "smali" / "com" / "example" / "game"
            (smali_dir / "a").mkdir(parents=True)
            (smali_dir / "NDK.smali").write_text(
                ".class Lcom/example/game/NDK;", encoding="utf-8"
            )
            (smali_dir / "a" / "b.smali").write_text(
                '.class Lcom/example/game/a/b;\nconst-string v0, "com.example.game.a.b"\n'
                'const-string v1, "com.example.game.NDK"\n'
                'const-string v2, "com.example.game.companion"\n'
                "const-string v3, "
                '"/Android/obb/com.example.game/main.1.com.example.game.obb"\n',
                encoding="utf-8",
            )
            manifest = decoded / "AndroidManifest.xml"
            manifest.write_text(
                """<manifest package="com.example.game">
    <queries><package android:name="com.example.game.companion"/>
        <package android:name="com.example.game"/></queries>
    <instrumentation android:targetPackage="com.example.game" android:name=".Runner"/>
    <application android:name=".NDK">
        <activity android:name=".a.b" android:parentActivityName=".NDK">
            <meta-data android:name="android.support.PARENT_ACTIVITY" android:value=".NDK"/>
        </activity>
        <activity android:name="Alias"
            android:targetActivity="com.example.game.companion.Main"/>
        <meta-data android:name="com.example.game.key" android:value="com.example.game"/>
    </application>
</manifest>
""",
                encoding="utf-8",
            )

            result = replace_package_references(
                decoded, "com.example.game", "com.example.game.dev", token=CancellationToken()
            )

            text = manifest.read_text(encoding="utf-8")
            self.assertIn('package="com.example.game.dev"', text)
            self.assertIn('<package android:name="com.example.game.companion"/>', text)
            self.assertIn('<package android:name="com.example.game.dev"/>', text)
            self.assertIn('android:targetPackage="com.example.game.dev"', text)
            self.assertIn('android:name="com.example.game.Runner"', text)
            self.assertIn('<application android:name="com.example.game.NDK">', text)
            self.assertIn('android:name="com.example.game.a.b"', text)
            self.assertIn('android:parentActivityName="com.example.game.NDK"', text)
            self.assertIn('android:value="com.example.game.NDK"', text)
            self.assertIn('android:targetActivity="com.example.game.companion.Main"', text)
            self.assertIn(
                'android:name="com.example.game.dev.key" android:value="com.example.game.dev"',
                text,
            )
            self.assertEqual(result.qualified_components, 6)
            smali = (smali_dir / "a" / "b.smali").read_text(encoding="utf-8")
            self.assertIn('"com.example.game.a.b"', smali)
            self.assertIn('"com.example.game.NDK"', smali)
            # A sibling package the code talks to is not part of this app's identity...
            # unless it is not code at all; without a smali path it is treated as identity.
            self.assertIn('"com.example.game.dev.companion"', smali)
            self.assertIn(
                '"/Android/obb/com.example.game.dev/main.1.com.example.game.dev.obb"', smali
            )

    def test_find_class_lookups_in_native_code_count_as_jni_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            decoded = Path(temporary)
            lib = decoded / "lib" / "arm64-v8a" / "libglue.so"
            lib.parent.mkdir(parents=True)
            lib.write_bytes(b"\x00com/example/game/Bridge\x00")

            self.assertEqual(
                find_jni_libraries(decoded, "com.example.game", CancellationToken()),
                ("lib/arm64-v8a/libglue.so",),
            )


if __name__ == "__main__":
    unittest.main()
