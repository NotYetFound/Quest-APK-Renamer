import tempfile
import unittest
from pathlib import Path

from quest_renamer.domain.operations import CancellationToken
from quest_renamer.infrastructure.package_rewriter import replace_package_references


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


if __name__ == "__main__":
    unittest.main()
