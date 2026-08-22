#!/usr/bin/env python3
"""Validate generated catalog coverage, links, IDs, and source parity."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from catalog_core import (
    MarkdownCatalogParser,
    catalog_digest,
    entry_fingerprint,
    fingerprint_fields,
)


class ValidationFailure(RuntimeError):
    pass


def validate(root: Path, source: Path | None = None) -> dict[str, int]:
    manifest_path = root / "references" / "catalog" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValidationFailure("manifest entries must be a non-empty list")
    ids = [item["id"] for item in entries]
    if len(ids) != len(set(ids)):
        raise ValidationFailure("manifest contains duplicate IDs")
    if manifest.get("schema_version") != 2 or manifest.get("generator_version") != 2:
        raise ValidationFailure("manifest must use catalog schema/generator version 2")

    referenced: set[Path] = set()
    auth_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    for item in entries:
        path = root / item["definition"]
        if not path.is_file():
            raise ValidationFailure(f"missing definition: {item['definition']}")
        definition = json.loads(path.read_text(encoding="utf-8"))
        if definition.get("id") != item["id"]:
            raise ValidationFailure(f"definition ID mismatch: {path}")
        if definition.get("schema_version") != 2:
            raise ValidationFailure(f"definition schema version mismatch: {path}")
        if definition.get("request", {}).get("base_url", "sentinel") is not None:
            raise ValidationFailure(f"generated base_url must remain null: {path}")
        expected_fingerprint = fingerprint_fields(
            api_id=definition["id"],
            name=definition["name"],
            category=definition["category"],
            description=definition["description"],
            documentation_url=definition["documentation_url"],
            auth=item["auth"],
            https=definition["transport"]["https"],
            cors=definition["transport"]["cors"],
        )
        if item.get("fingerprint") != expected_fingerprint:
            raise ValidationFailure(f"manifest fingerprint mismatch: {path}")
        if definition.get("source", {}).get("fingerprint") != expected_fingerprint:
            raise ValidationFailure(f"definition fingerprint mismatch: {path}")
        for field in ("name", "category", "description"):
            if definition.get(field) != item.get(field):
                raise ValidationFailure(f"definition {field} mismatch: {path}")
        referenced.add(path.resolve())
        auth_counts[item["auth"]] += 1
        category_counts[item["category"]] += 1

    actual = {path.resolve() for path in (root / "references" / "apis").glob("*/*.json")}
    if actual != referenced:
        missing = referenced - actual
        extra = actual - referenced
        raise ValidationFailure(f"definition coverage mismatch; missing={len(missing)}, extra={len(extra)}")
    counts = manifest.get("counts", {})
    if counts.get("apis") != len(entries) or counts.get("categories") != len(category_counts):
        raise ValidationFailure("manifest summary counts are incorrect")
    if counts.get("authentication") != dict(sorted(auth_counts.items())):
        raise ValidationFailure("manifest authentication counts are incorrect")

    index = root / "references" / "catalog" / "INDEX.md"
    if not index.is_file():
        raise ValidationFailure("master category index is missing")
    for category in category_counts:
        from catalog_core import slugify

        category_slug = slugify(category)
        category_index = root / "references" / "catalog" / f"{category_slug}.md"
        if not category_index.is_file():
            raise ValidationFailure(f"category index is missing: {category}")
        category_text = category_index.read_text(encoding="utf-8")
        category_entries = [item for item in entries if item["category"] == category]
        for item in category_entries:
            api_slug = item["id"].split("/", 1)[1]
            expected_link = f"../apis/{category_slug}/{api_slug}.json"
            if expected_link not in category_text:
                raise ValidationFailure(
                    f"category index does not link {item['id']}: {category_index}"
                )

    if source:
        parsed = MarkdownCatalogParser().parse(source.read_text(encoding="utf-8"))
        parsed_fingerprints = [entry_fingerprint(entry) for entry in parsed]
        manifest_fingerprints = [item.get("fingerprint") for item in entries]
        if parsed_fingerprints != manifest_fingerprints:
            raise ValidationFailure("manifest does not exactly match the supplied upstream source")
        if manifest.get("source", {}).get("catalog_digest") != catalog_digest(parsed):
            raise ValidationFailure("manifest catalog digest does not match upstream source")

    return {"apis": len(entries), "categories": len(category_counts), "definitions": len(actual)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    try:
        result = validate(args.root.resolve(), args.source)
    except (OSError, json.JSONDecodeError, ValidationFailure, ValueError) as exc:
        parser.exit(1, f"validation failed: {exc}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
