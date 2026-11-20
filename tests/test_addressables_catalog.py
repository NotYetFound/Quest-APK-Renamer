import struct
import unittest

from expansion_fixtures import (
    DYNAMIC_FLAG,
    CatalogBuilder,
    build_catalog,
    build_plain_catalog,
    finish_catalog,
)

from quest_renamer.infrastructure.addressables_catalog import (
    AddressablesCatalogError,
    resolve_catalog_internal_ids,
    rewrite_catalog_paths,
)

OLD = "com.MightyCoconut.WalkaboutMiniGolf"
NEW = "com.mr.MightyCoconut.WalkaboutMiniGolf"
TAG = "999999"
OBB_NAME = f"main.{TAG}.{OLD}.obb"


class CatalogRewriteTests(unittest.TestCase):
    def test_shared_dynamic_component_is_repointed_once(self) -> None:
        builder = CatalogBuilder()
        old_component = builder.string(OLD)
        shared_tail = builder.record(old_component)
        head = [
            builder.record(builder.string(name), shared_tail) | DYNAMIC_FLAG
            for name in ("alpha", "beta")
        ]
        catalog = finish_catalog(builder, head)
        before = resolve_catalog_internal_ids(catalog)
        self.assertEqual(
            sorted(before), sorted([f"{OLD}/alpha", f"{OLD}/beta"])
        )

        patch = rewrite_catalog_paths(catalog, OLD, NEW)

        self.assertIsNotNone(patch)
        assert patch is not None
        self.assertEqual(patch.repointed_records, 1)
        self.assertEqual(patch.internal_ids, 2)
        self.assertEqual(len(patch.data), len(catalog) + 4 + len(NEW))
        after = resolve_catalog_internal_ids(patch.data)
        self.assertEqual(
            sorted(after), sorted(value.replace(OLD, NEW) for value in before)
        )
        self.assertFalse(any(OLD in value for value in after))
        self.assertIn(OLD.encode(), patch.data)

    def test_already_current_catalog_is_left_alone(self) -> None:
        catalog = build_catalog([[NEW, "content"]])
        self.assertIsNone(rewrite_catalog_paths(catalog, OLD, NEW))

    def test_equal_packages_are_a_no_op(self) -> None:
        catalog = build_catalog([[OLD, "content"]])
        self.assertIsNone(rewrite_catalog_paths(catalog, OLD, OLD))

    def test_package_inside_a_longer_component_is_refused(self) -> None:
        catalog = build_catalog([[f"prefix-{OLD}-suffix", "content"]])
        with self.assertRaisesRegex(AddressablesCatalogError, "longer catalog string"):
            rewrite_catalog_paths(catalog, OLD, NEW)

    def test_expansion_filename_components_are_not_guessed(self) -> None:
        catalog = build_catalog([[OBB_NAME, "content"]])
        with self.assertRaisesRegex(AddressablesCatalogError, "longer catalog string"):
            rewrite_catalog_paths(catalog, OLD, NEW)

    def test_plain_stored_internal_id_is_refused(self) -> None:
        catalog = build_plain_catalog(OLD)
        with self.assertRaisesRegex(AddressablesCatalogError, "single stored internal ID"):
            rewrite_catalog_paths(catalog, OLD, NEW)

    def test_target_that_extends_the_source_package_is_allowed(self) -> None:
        catalog = build_catalog([[OLD, "content"]])
        target = f"{OLD}.dev"

        patch = rewrite_catalog_paths(catalog, OLD, target)

        self.assertIsNotNone(patch)
        assert patch is not None
        self.assertEqual(resolve_catalog_internal_ids(patch.data), (f"{target}/content",))

    def test_bad_catalog_signature_is_refused(self) -> None:
        catalog = bytearray(build_catalog([[OLD, "content"]]))
        struct.pack_into("<I", catalog, 0, 0xDEADBEEF)
        with self.assertRaisesRegex(AddressablesCatalogError, "unexpected signature"):
            resolve_catalog_internal_ids(bytes(catalog))


if __name__ == "__main__":
    unittest.main()
