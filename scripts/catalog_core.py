#!/usr/bin/env python3
"""Core catalog model, parser, and deterministic naming algorithms."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import blake2s, sha256
import json
import re
import unicodedata
from typing import Iterable, Iterator


UPSTREAM_REPOSITORY = "https://github.com/public-apis/public-apis"


@dataclass(frozen=True)
class CatalogEntry:
    name: str
    description: str
    documentation_url: str
    auth: str
    https: str
    cors: str
    category: str
    source_line: int
    api_id: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def fingerprint_fields(
    *,
    api_id: str,
    name: str,
    category: str,
    description: str,
    documentation_url: str,
    auth: str,
    https: str,
    cors: str,
) -> str:
    """Hash only semantic interface fields, never volatile source positions."""
    payload = {
        "id": api_id,
        "name": name,
        "category": category,
        "description": description,
        "documentation_url": documentation_url,
        "auth": auth,
        "https": https,
        "cors": cors,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def entry_fingerprint(entry: CatalogEntry) -> str:
    return fingerprint_fields(
        api_id=entry.api_id,
        name=entry.name,
        category=entry.category,
        description=entry.description,
        documentation_url=entry.documentation_url,
        auth=entry.auth,
        https=entry.https,
        cors=entry.cors,
    )


def catalog_digest(entries: Iterable[CatalogEntry]) -> str:
    """Hash the ordered catalog so additions, removals, edits, and moves are detected."""
    digest = sha256()
    for entry in entries:
        digest.update(entry_fingerprint(entry).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def slugify(value: str) -> str:
    """Return a stable, path-safe Unicode-to-ASCII slug."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    if slug:
        return slug
    digest = blake2s(value.encode("utf-8"), digest_size=5).hexdigest()
    return f"item-{digest}"


class SlugRegistry:
    """Allocate deterministic IDs and resolve duplicate names per category."""

    def assign(self, entries: Iterable[CatalogEntry]) -> list[CatalogEntry]:
        materialized = list(entries)
        groups: dict[tuple[str, str], list[CatalogEntry]] = {}
        for entry in materialized:
            key = (slugify(entry.category), slugify(entry.name))
            groups.setdefault(key, []).append(entry)

        result: list[CatalogEntry] = []
        used: set[str] = set()
        for entry in materialized:
            category_slug = slugify(entry.category)
            base = slugify(entry.name)
            candidates = groups[(category_slug, base)]
            if len(candidates) > 1:
                digest = blake2s(
                    entry.documentation_url.encode("utf-8"), digest_size=4
                ).hexdigest()
                base = f"{base}--{digest}"
            api_id = f"{category_slug}/{base}"
            if api_id in used:
                digest = blake2s(
                    f"{entry.documentation_url}:{entry.source_line}".encode("utf-8"),
                    digest_size=4,
                ).hexdigest()
                api_id = f"{category_slug}/{base}--{digest}"
            used.add(api_id)
            result.append(
                CatalogEntry(
                    **{**entry.to_dict(), "api_id": api_id},
                )
            )
        return result


def split_markdown_row(line: str) -> list[str]:
    """Split a Markdown table row while respecting escapes and code spans."""
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    cells: list[str] = []
    buffer: list[str] = []
    escaped = False
    in_code = False
    for char in text:
        if escaped:
            buffer.append(char)
            escaped = False
        elif char == "\\":
            buffer.append(char)
            escaped = True
        elif char == "`":
            in_code = not in_code
            buffer.append(char)
        elif char == "|" and not in_code:
            cells.append("".join(buffer).strip())
            buffer = []
        else:
            buffer.append(char)
    cells.append("".join(buffer).strip())
    return cells


def parse_markdown_link(cell: str) -> tuple[str, str]:
    match = re.match(r"^\[([^]]+)]\((.+)\)$", cell.strip())
    if not match:
        raise ValueError(f"expected a Markdown link, got: {cell!r}")
    return match.group(1).strip(), match.group(2).strip()


def normalize_enum(value: str) -> str:
    return value.strip().strip("`").strip()


class MarkdownCatalogParser:
    """Parse category API tables with a small explicit state machine."""

    HEADER = ("api", "description", "auth", "https", "cors")

    def parse(self, text: str) -> list[CatalogEntry]:
        entries: list[CatalogEntry] = []
        category: str | None = None
        after_index = False
        in_table = False

        for line_number, line in enumerate(text.splitlines(), start=1):
            if line.strip() == "## Index":
                after_index = True
                category = None
                in_table = False
                continue
            if not after_index:
                continue
            if line.startswith("## ") and not line.startswith("### "):
                category = None
                in_table = False
                continue
            if line.startswith("### "):
                category = line[4:].strip()
                in_table = False
                continue
            if category is None:
                continue

            cells = split_markdown_row(line) if "|" in line else []
            lowered = tuple(cell.lower() for cell in cells[:5])
            if lowered == self.HEADER:
                in_table = True
                continue
            if in_table and cells and all(re.fullmatch(r":?-{3,}:?", c) for c in cells[:5]):
                continue
            if not in_table:
                continue
            if not line.lstrip().startswith("|"):
                in_table = False
                continue
            if len(cells) < 5:
                raise ValueError(f"line {line_number}: expected five table columns")

            name, url = parse_markdown_link(cells[0])
            auth = normalize_enum(cells[2])
            https = normalize_enum(cells[3]).lower()
            cors = normalize_enum(cells[4]).lower()
            if not auth:
                raise ValueError(f"line {line_number}: empty auth value")
            if https not in {"yes", "no", "unknown"}:
                raise ValueError(f"line {line_number}: unsupported HTTPS value {https!r}")
            if cors not in {"yes", "no", "unknown", "n/a"}:
                raise ValueError(f"line {line_number}: unsupported CORS value {cors!r}")
            entries.append(
                CatalogEntry(
                    name=name,
                    description=cells[1].strip(),
                    documentation_url=url,
                    auth=auth,
                    https=https,
                    cors=cors,
                    category=category,
                    source_line=line_number,
                )
            )

        if not entries:
            raise ValueError("no API entries found after the upstream Index")
        return SlugRegistry().assign(entries)


def auth_descriptor(entry: CatalogEntry) -> dict[str, object]:
    auth_type = entry.auth
    normalized = auth_type.lower()
    api_token = entry.api_id.replace("/", "__").replace("-", "_").upper()
    if normalized == "no":
        return {"type": "none", "required": False, "strategy": "none"}
    if normalized == "oauth":
        return {
            "type": auth_type,
            "required": True,
            "strategy": "bearer",
            "credential_env": f"PUBLIC_API__{api_token}__TOKEN",
        }
    if normalized == "user-agent":
        return {
            "type": auth_type,
            "required": True,
            "strategy": "header",
            "header": "User-Agent",
            "credential_env": f"PUBLIC_API__{api_token}__USER_AGENT",
        }
    header = "X-Mashape-Key" if normalized == "x-mashape-key" else None
    return {
        "type": auth_type,
        "required": True,
        "strategy": "header" if header else "configurable",
        "header": header,
        "credential_env": f"PUBLIC_API__{api_token}__API_KEY",
    }
