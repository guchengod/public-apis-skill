from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from catalog_core import MarkdownCatalogParser, SlugRegistry, auth_descriptor
from sync_catalog import CatalogEmitter


SAMPLE = """# Catalog
## Index
* [Animals](#animals)
### Animals
API | Description | Auth | HTTPS | CORS
|:---|:---|:---|:---|:---|
| [Cat Facts](https://one.example/docs) | Facts | No | Yes | Yes |
| [Cat Facts](https://two.example/docs) | More facts | `apiKey` | Yes | Unknown | |
### Science & Math
API | Description | Auth | HTTPS | CORS |
|:---|:---|:---|:---|:---|
| [Formula](https://formula.example) | Math | `OAuth` | No | No |
"""


class CatalogTests(unittest.TestCase):
    def test_parser_and_collision_algorithm(self) -> None:
        entries = MarkdownCatalogParser().parse(SAMPLE)
        self.assertEqual(3, len(entries))
        self.assertEqual("animals", entries[0].api_id.split("/")[0])
        self.assertNotEqual(entries[0].api_id, entries[1].api_id)
        self.assertTrue(entries[0].api_id.startswith("animals/cat-facts--"))
        self.assertEqual("science-math/formula", entries[2].api_id)

    def test_auth_descriptors(self) -> None:
        entries = MarkdownCatalogParser().parse(SAMPLE)
        self.assertEqual("none", auth_descriptor(entries[0])["strategy"])
        self.assertEqual("configurable", auth_descriptor(entries[1])["strategy"])
        self.assertEqual("bearer", auth_descriptor(entries[2])["strategy"])

    def test_ids_are_deterministic(self) -> None:
        first = MarkdownCatalogParser().parse(SAMPLE)
        second = MarkdownCatalogParser().parse(SAMPLE)
        self.assertEqual([e.api_id for e in first], [e.api_id for e in second])

    def test_same_catalog_at_new_revision_is_noop(self) -> None:
        entries = MarkdownCatalogParser().parse(SAMPLE)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertTrue(CatalogEmitter(root, "revision-a").emit(entries))
            snapshot = {
                path.relative_to(root): path.read_bytes()
                for path in root.glob("references/**/*")
                if path.is_file()
            }
            self.assertFalse(CatalogEmitter(root, "revision-b").emit(entries))
            second_snapshot = {
                path.relative_to(root): path.read_bytes()
                for path in root.glob("references/**/*")
                if path.is_file()
            }
            self.assertEqual(snapshot, second_snapshot)

    def test_metadata_edit_changes_only_one_interface_definition(self) -> None:
        before = MarkdownCatalogParser().parse(SAMPLE)
        after = MarkdownCatalogParser().parse(SAMPLE.replace("| Facts |", "| Updated facts |"))
        with TemporaryDirectory() as directory:
            root = Path(directory)
            CatalogEmitter(root, "revision-a").emit(before)
            old_definitions = {
                path.relative_to(root): path.read_bytes()
                for path in root.glob("references/apis/*/*.json")
            }
            CatalogEmitter(root, "revision-b").emit(after)
            new_definitions = {
                path.relative_to(root): path.read_bytes()
                for path in root.glob("references/apis/*/*.json")
            }
            changed = [
                path
                for path in old_definitions
                if old_definitions[path] != new_definitions[path]
            ]
            self.assertEqual(1, len(changed))

    def test_missing_definition_forces_self_healing_rebuild(self) -> None:
        entries = MarkdownCatalogParser().parse(SAMPLE)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            CatalogEmitter(root, "revision-a").emit(entries)
            missing = next(root.glob("references/apis/*/*.json"))
            missing.unlink()
            self.assertTrue(CatalogEmitter(root, "revision-b").emit(entries))
            self.assertTrue(missing.is_file())


if __name__ == "__main__":
    unittest.main()
