#!/usr/bin/env python3
"""Synchronize all public-apis README entries into the three-layer skill."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Iterator
from urllib.request import Request, urlopen

from catalog_core import (
    CatalogEntry,
    MarkdownCatalogParser,
    UPSTREAM_REPOSITORY,
    auth_descriptor,
    catalog_digest,
    entry_fingerprint,
    slugify,
)


DEFAULT_SOURCE = "https://raw.githubusercontent.com/public-apis/public-apis/master/README.md"
GENERATOR_VERSION = 2


class CatalogSource:
    def read(self) -> str:
        raise NotImplementedError


class FileSource(CatalogSource):
    def __init__(self, path: Path):
        self.path = path

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8")


class HttpSource(CatalogSource):
    def __init__(self, url: str):
        self.url = url

    def read(self) -> str:
        request = Request(self.url, headers={"User-Agent": "public-api-skill-sync/1.0"})
        with urlopen(request, timeout=60) as response:
            return response.read().decode("utf-8")


def source_for(value: str) -> CatalogSource:
    if value.startswith(("https://", "http://")):
        return HttpSource(value)
    return FileSource(Path(value).expanduser().resolve())


class GeneratedTreeTransaction:
    """Build generated outputs off-tree and swap them with rollback."""

    TARGETS = ("catalog", "apis")

    def __init__(self, references_dir: Path):
        self.references_dir = references_dir

    @contextmanager
    def staging(self) -> Iterator[Path]:
        self.references_dir.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".public-api-stage-", dir=self.references_dir))
        try:
            yield stage
            self._commit(stage)
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def _commit(self, stage: Path) -> None:
        backup = Path(tempfile.mkdtemp(prefix=".public-api-backup-", dir=self.references_dir))
        moved_old: list[str] = []
        moved_new: list[str] = []
        try:
            for name in self.TARGETS:
                target = self.references_dir / name
                staged = stage / name
                if not staged.is_dir():
                    raise RuntimeError(f"staged target is missing: {staged}")
                if target.exists():
                    os.replace(target, backup / name)
                    moved_old.append(name)
                os.replace(staged, target)
                moved_new.append(name)
        except Exception:
            for name in reversed(moved_new):
                target = self.references_dir / name
                if target.exists():
                    shutil.rmtree(target)
            for name in reversed(moved_old):
                os.replace(backup / name, self.references_dir / name)
            raise
        finally:
            shutil.rmtree(backup, ignore_errors=True)


class CatalogEmitter:
    def __init__(self, root: Path, revision: str, *, force: bool = False):
        self.root = root
        self.revision = revision
        self.force = force

    def emit(self, entries: list[CatalogEntry]) -> bool:
        references = self.root / "references"
        digest = catalog_digest(entries)
        if not self.force and self._is_current(references, digest):
            return False
        with GeneratedTreeTransaction(references).staging() as stage:
            catalog_dir = stage / "catalog"
            apis_dir = stage / "apis"
            catalog_dir.mkdir()
            apis_dir.mkdir()
            manifest_entries = []
            grouped: dict[str, list[CatalogEntry]] = defaultdict(list)
            for entry in entries:
                grouped[entry.category].append(entry)
                definition_path = self._write_definition(apis_dir, entry)
                manifest_entries.append(
                    {
                        "id": entry.api_id,
                        "name": entry.name,
                        "category": entry.category,
                        "description": entry.description,
                        "auth": entry.auth,
                        "https": entry.https,
                        "cors": entry.cors,
                        "fingerprint": entry_fingerprint(entry),
                        "definition": f"references/apis/{definition_path.as_posix()}",
                    }
                )

            manifest = {
                "schema_version": 2,
                "generator_version": GENERATOR_VERSION,
                "source": {
                    "repository": UPSTREAM_REPOSITORY,
                    "revision": self.revision,
                    "catalog_digest": digest,
                },
                "counts": {
                    "apis": len(entries),
                    "categories": len(grouped),
                    "authentication": dict(sorted(Counter(e.auth for e in entries).items())),
                },
                "entries": manifest_entries,
            }
            self._write_json(catalog_dir / "manifest.json", manifest)
            self._write_indexes(catalog_dir, grouped, entries)
            self._validate_stage(stage, manifest)
        return True

    @staticmethod
    def _is_current(references: Path, digest: str) -> bool:
        manifest_path = references / "catalog" / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return False
        if not (
            manifest.get("generator_version") == GENERATOR_VERSION
            and manifest.get("source", {}).get("catalog_digest") == digest
        ):
            return False
        entries = manifest.get("entries")
        if not isinstance(entries, list) or not (references / "catalog" / "INDEX.md").is_file():
            return False
        actual_definitions = list((references / "apis").glob("*/*.json"))
        if len(actual_definitions) != len(entries):
            return False
        try:
            for item in entries:
                relative = str(item["definition"]).removeprefix("references/")
                definition = json.loads((references / relative).read_text(encoding="utf-8"))
                if definition.get("source", {}).get("fingerprint") != item.get("fingerprint"):
                    return False
        except (KeyError, FileNotFoundError, json.JSONDecodeError, OSError):
            return False
        return True

    def _write_definition(self, apis_dir: Path, entry: CatalogEntry) -> Path:
        category_slug, api_slug = entry.api_id.split("/", 1)
        relative = Path(category_slug) / f"{api_slug}.json"
        payload = {
            "schema_version": 2,
            "id": entry.api_id,
            "name": entry.name,
            "category": entry.category,
            "description": entry.description,
            "documentation_url": entry.documentation_url,
            "auth": auth_descriptor(entry),
            "transport": {"https": entry.https, "cors": entry.cors},
            "request": {"base_url": None, "default_method": "GET"},
            "source": {
                "repository": UPSTREAM_REPOSITORY,
                "fingerprint": entry_fingerprint(entry),
            },
        }
        self._write_json(apis_dir / relative, payload)
        return relative

    def _write_indexes(
        self,
        catalog_dir: Path,
        grouped: dict[str, list[CatalogEntry]],
        entries: list[CatalogEntry],
    ) -> None:
        lines = [
            "# Public API catalog",
            "",
            f"Generated from `{UPSTREAM_REPOSITORY}` at `{self.revision}`.",
            f"Contains **{len(entries)} APIs** in **{len(grouped)} categories**.",
            "",
            "Read one category index, then load only the selected JSON definitions.",
            "",
            "| Category | APIs | Index |",
            "|---|---:|---|",
        ]
        for category in sorted(grouped, key=str.casefold):
            slug = slugify(category)
            lines.append(f"| {category} | {len(grouped[category])} | [{slug}.md]({slug}.md) |")
            category_lines = [
                f"# {category}",
                "",
                f"{len(grouped[category])} interfaces. Paths are relative to this catalog file.",
                "",
                "| API | Auth | HTTPS | CORS | Interface |",
                "|---|---|---|---|---|",
            ]
            for entry in grouped[category]:
                _, api_slug = entry.api_id.split("/", 1)
                target = f"../apis/{slug}/{api_slug}.json"
                category_lines.append(
                    f"| {entry.name} | {entry.auth} | {entry.https} | {entry.cors} | "
                    f"[`{entry.api_id}`]({target}) |"
                )
            (catalog_dir / f"{slug}.md").write_text(
                "\n".join(category_lines) + "\n", encoding="utf-8"
            )
        (catalog_dir / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _validate_stage(self, stage: Path, manifest: dict[str, object]) -> None:
        manifest_entries = manifest["entries"]
        assert isinstance(manifest_entries, list)
        ids = [entry["id"] for entry in manifest_entries]
        if len(ids) != len(set(ids)):
            raise RuntimeError("generated API IDs are not unique")
        files = list((stage / "apis").glob("*/*.json"))
        if len(files) != len(ids):
            raise RuntimeError(f"definition count mismatch: {len(files)} != {len(ids)}")
        for item in manifest_entries:
            definition = str(item["definition"]).removeprefix("references/apis/")
            if not (stage / "apis" / definition).is_file():
                raise RuntimeError(f"missing generated definition: {definition}")

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="README path or HTTP(S) URL")
    parser.add_argument("--revision", default="master", help="source Git revision or label")
    parser.add_argument(
        "--force",
        action="store_true",
        help="rebuild even when the semantic catalog digest is unchanged",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="skill root",
    )
    args = parser.parse_args()
    text = source_for(args.source).read()
    entries = MarkdownCatalogParser().parse(text)
    changed = CatalogEmitter(
        args.root.resolve(), args.revision, force=args.force
    ).emit(entries)
    status = "generated" if changed else "unchanged"
    print(f"{status}: {len(entries)} APIs across {len({e.category for e in entries})} categories")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
