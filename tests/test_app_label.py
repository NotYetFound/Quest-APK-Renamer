import tempfile
import unittest
from pathlib import Path

from quest_renamer.infrastructure.app_label import (
    AppLabelError,
    apply_app_label,
    escape_android_string,
    resolve_label,
)

MANIFEST_REF = """<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.example.game">
    <application android:label="@string/app_name" android:icon="@mipmap/ic">
        <activity android:name=".Main" android:label="@string/app_name"/>
    </application>
</manifest>
"""

MANIFEST_LITERAL = """<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.example.game">
    <application android:label="Tom &amp; Jerry">
        <activity android:name=".Main" android:label="Tom &amp; Jerry"/>
        <activity android:name=".Other" android:label="Settings"/>
    </application>
</manifest>
"""


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class AppLabelTests(unittest.TestCase):
    def test_suffix_is_appended_to_every_locale_of_a_string_resource(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write(root, "AndroidManifest.xml", MANIFEST_REF)
            default = _write(
                root,
                "res/values/strings.xml",
                '<resources>\n    <string name="app_name">Space Game</string>\n'
                '    <string name="app_name_short">SG</string>\n</resources>\n',
            )
            french = _write(
                root,
                "res/values-fr/strings.xml",
                '<resources><string name="app_name">Jeu de l\\\'espace</string></resources>',
            )
            other_xml = '<resources><string name="x">y</string></resources>'
            other = _write(root, "res/values-de/other.xml", other_xml)

            previous, new = apply_app_label(root, suffix="(Dev)")

            self.assertEqual((previous, new), ("Space Game", "Space Game (Dev)"))
            self.assertIn(
                '<string name="app_name">Space Game (Dev)</string>',
                default.read_text(encoding="utf-8"),
            )
            self.assertIn('<string name="app_name_short">SG</string>', default.read_text())
            self.assertIn(
                "<string name=\"app_name\">Jeu de l\\'espace (Dev)</string>",
                french.read_text(encoding="utf-8"),
            )
            self.assertEqual(other.read_text(), other_xml)

    def test_explicit_label_replaces_the_name_and_is_escaped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write(root, "AndroidManifest.xml", MANIFEST_REF)
            default = _write(
                root,
                "res/values/strings.xml",
                '<resources><string name="app_name">Space Game</string></resources>',
            )

            previous, new = apply_app_label(root, label="Rock & Roll's \"Copy\"", suffix="(x)")

            self.assertEqual(previous, "Space Game")
            self.assertEqual(new, "Rock & Roll's \"Copy\"")
            self.assertIn(
                "<string name=\"app_name\">Rock &amp; Roll\\'s \\\"Copy\\\"</string>",
                default.read_text(encoding="utf-8"),
            )

    def test_literal_manifest_label_is_changed_on_application_and_matching_activities(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = _write(root, "AndroidManifest.xml", MANIFEST_LITERAL)

            previous, new = apply_app_label(root, suffix="(Dev)")

            self.assertEqual((previous, new), ("Tom & Jerry", "Tom & Jerry (Dev)"))
            text = manifest.read_text(encoding="utf-8")
            self.assertEqual(text.count('android:label="Tom &amp; Jerry (Dev)"'), 2)
            self.assertIn('android:label="Settings"', text)

    def test_nothing_requested_changes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = _write(root, "AndroidManifest.xml", MANIFEST_LITERAL)

            self.assertEqual(apply_app_label(root), ("", ""))
            self.assertEqual(manifest.read_text(encoding="utf-8"), MANIFEST_LITERAL)

    def test_framework_and_missing_labels_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write(
                root,
                "AndroidManifest.xml",
                MANIFEST_REF.replace("@string/app_name", "@android:string/ok"),
            )
            with self.assertRaisesRegex(AppLabelError, "framework resource"):
                apply_app_label(root, suffix="(Dev)")

            _write(root, "AndroidManifest.xml", MANIFEST_REF)
            with self.assertRaisesRegex(AppLabelError, "was not found"):
                apply_app_label(root, suffix="(Dev)")

    def test_string_arrays_and_cdata_bodies_are_handled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write(root, "AndroidManifest.xml", MANIFEST_REF)
            strings = _write(
                root,
                "res/values/strings.xml",
                '<resources>\n<string-array name="app_name"><item>x</item></string-array>\n'
                '<string name="other">O</string>\n'
                '<string name="app_name"><![CDATA[Cool & Game]]></string>\n</resources>\n',
            )

            previous, new = apply_app_label(root, suffix="(Dev)")

            self.assertEqual((previous, new), ("Cool & Game", "Cool & Game (Dev)"))
            text = strings.read_text(encoding="utf-8")
            self.assertIn('<string-array name="app_name"><item>x</item></string-array>', text)
            self.assertIn('<string name="other">O</string>', text)
            self.assertIn(
                '<string name="app_name"><![CDATA[Cool & Game (Dev)]]></string>', text
            )

    def test_helpers(self) -> None:
        self.assertEqual(resolve_label(" Custom ", "(x)", "Orig"), "Custom")
        self.assertEqual(resolve_label("", " (x) ", "Orig"), "Orig (x)")
        self.assertEqual(resolve_label("", "(x)", ""), "")
        self.assertEqual(escape_android_string("@home <b>"), "\\@home &lt;b&gt;")


if __name__ == "__main__":
    unittest.main()
