import tempfile
import unittest
from pathlib import Path

from quest_renamer.domain.operations import CancellationToken
from quest_renamer.domain.signers import (
    DN_VALUE_MAX_LENGTH,
    SignerIdentity,
    build_lineage_dn,
    describe_previous_signer,
    identify_signer,
    rename_signature_text,
)
from quest_renamer.infrastructure.process_runner import CommandResult
from quest_renamer.infrastructure.signer_inspection import (
    load_signer_registry,
    parse_signature_details,
    parse_signer_identity,
)
from quest_renamer.infrastructure.signing_identity import SigningIdentityStore


class KeyWritingRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def run(self, arguments: object, **_kwargs: object) -> CommandResult:
        command = tuple(str(value) for value in arguments)  # type: ignore[union-attr]
        Path(command[command.index("-keystore") + 1]).write_bytes(b"keystore")
        self.commands.append(command)
        return CommandResult(command, 0, ())


class SignerLineageTests(unittest.TestCase):
    def test_lineage_dn_embeds_the_previous_signer_and_rename_tag(self) -> None:
        dn = build_lineage_dn(
            signature_text="mr",
            previous=("NothingIsFree", "NIF"),
        )

        self.assertIn("CN=Quest APK Renamer", dn)
        self.assertIn("OU=mr", dn)
        self.assertIn("O=QAR", dn)
        self.assertIn("L=Previously signed by NothingIsFree (NIF)", dn)

    def test_lineage_dn_falls_back_sanitizes_and_caps_values(self) -> None:
        fresh = build_lineage_dn(previous=None)
        unsafe = build_lineage_dn(
            signature_text='ta"g;+',
            previous=("Na\\me <Inc>", "lab=el"),
        )
        long = build_lineage_dn(previous=("A" * 500, "label"))

        self.assertIn("L=Fresh rename", fresh)
        for reserved in '"\\<>;+':
            self.assertNotIn(reserved, unsafe)
        self.assertEqual(unsafe.count("="), 4)
        self.assertEqual(unsafe.count(","), 3)
        self.assertLessEqual(len(long.split("L=", 1)[1]), DN_VALUE_MAX_LENGTH)

    def test_previous_signer_description_ignores_unknown_identities(self) -> None:
        self.assertIsNone(describe_previous_signer(None))
        self.assertIsNone(
            describe_previous_signer(SignerIdentity("unknown", "Someone", "Someone"))
        )
        self.assertEqual(
            describe_previous_signer(SignerIdentity("nif", "NIF", "NothingIsFree")),
            ("NothingIsFree", "NIF"),
        )

    def test_registry_matches_cn_and_o_but_not_ou_or_lineage_fields(self) -> None:
        registry = load_signer_registry(
            Path(__file__).parents[1]
            / "src"
            / "quest_renamer"
            / "resources"
            / "known-signers.json"
        )
        identity = identify_signer(
            "CN=Quest APK Renamer, OU=NothingIsFree, O=QAR, "
            "L=Previously signed by NothingIsFree (NIF)",
            None,
            registry,
        )

        self.assertIsNotNone(identity)
        assert identity is not None
        self.assertEqual(identity.id, "quest_apk_renamer")

    def test_seed_registry_recognizes_every_added_signer(self) -> None:
        registry = load_signer_registry(
            Path(__file__).parents[1]
            / "src"
            / "quest_renamer"
            / "resources"
            / "known-signers.json"
        )
        cases = {
            "CN=Automagic Package Changer, O=APC": "automagic",
            "CN=NotQuestUnderground, O=VRP": "vrp",
            "CN=NothingIsFree, O=NIF": "nif",
            "CN=JF, O=vrSrc": "vrsrc",
        }

        for subject, expected in cases.items():
            with self.subTest(subject=subject):
                identity = parse_signer_identity(
                    f"Signer #1 certificate DN: {subject}", registry
                )
                self.assertIsNotNone(identity)
                assert identity is not None
                self.assertEqual(identity.id, expected)

    def test_signature_details_parse_schemes_and_certificate_hashes(self) -> None:
        registry = load_signer_registry(
            Path(__file__).parents[1]
            / "src"
            / "quest_renamer"
            / "resources"
            / "known-signers.json"
        )
        output = "\n".join(
            (
                "Verified using v1 scheme (JAR signing): true",
                "Verified using v2 scheme (APK Signature Scheme v2): true",
                "Signer #1 certificate DN: CN=Quest APK Renamer, OU=mr, O=QAR, "
                "L=Previously signed by NothingIsFree (NIF)",
                "Signer #1 certificate issuer: CN=NothingIsFree, O=NIF",
                "Signer #1 certificate SHA-256 digest: " + "a" * 64,
                "Signer #1 certificate SHA-1 digest: " + "b" * 40,
            )
        )

        result = parse_signature_details(output, registry)

        self.assertTrue(result.verified)
        self.assertEqual(result.schemes, ("v1", "v2"))
        self.assertEqual(result.certificates[0].sha256, "a" * 64)
        self.assertEqual(result.certificates[0].sha1, "b" * 40)
        self.assertEqual(result.identity.id, "quest_apk_renamer")  # type: ignore[union-attr]
        self.assertEqual(result.lineage, "Previously signed by NothingIsFree (NIF)")

    def test_signature_text_describes_inserted_tag_and_appended_suffix(self) -> None:
        self.assertEqual(rename_signature_text("com.studio.game", "com.mr.studio.game"), "mr")
        self.assertEqual(rename_signature_text("com.studio.game", "com.studio.gamea"), "a")
        self.assertEqual(
            rename_signature_text("com.studio.game", "com.studio.game"),
            "Renamed build",
        )

    def test_lineage_keystores_are_cached_by_the_full_dn(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            keytool = root / "keytool"
            keytool.touch()
            runner = KeyWritingRunner()
            store = SigningIdentityStore(
                root / "signing",
                keytool,
                runner=runner,  # type: ignore[arg-type]
            )
            dname = build_lineage_dn(previous=("NothingIsFree", "NIF"))

            first = store.load_or_create(token=CancellationToken(), dname=dname)
            second = store.load_or_create(token=CancellationToken(), dname=dname)

            self.assertEqual(first, second)
            self.assertEqual(first.keystore.parent.name, "lineage-keys")
            self.assertIn(dname, runner.commands[-1])
            # One canonical identity plus one lineage identity, each generated once.
            self.assertEqual(len(runner.commands), 2)


if __name__ == "__main__":
    unittest.main()
