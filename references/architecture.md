# Architecture and schemas

## Three logical layers

- Layer 1 — `SKILL.md`: concise selection, routing, and safety instructions.
- Layer 2 — `references/catalog/`: generated master manifest and category indexes.
- Layer 3 — `references/apis/<category>/<api>.json`: one generated interface definition for every upstream catalog row.

The generated files are not edited by hand. `scripts/sync_catalog.py` is their source of truth.
Catalog data retains the upstream MIT terms in the root `LICENSE`.

## Design

The synchronization pipeline applies four isolated components:

1. Source adapters normalize local files and HTTP URLs.
2. `MarkdownCatalogParser` is a state machine that accepts only the five-column category tables after the upstream Index.
3. `SlugRegistry` normalizes Unicode names and resolves duplicate slugs with a deterministic BLAKE2 digest of the documentation URL.
4. `GeneratedTreeTransaction` renders into a temporary tree, validates it, then swaps both generated directories. A failed build leaves the previous catalog intact.

The runtime applies a Registry facade over the generated manifest, a provider chain for configuration and environment credentials, Strategy objects for `No`, `apiKey`, `OAuth`, `X-Mashape-Key`, and `User-Agent` authentication, and an explicit proxy policy that supports global defaults and per-API overrides.

## Interface definition

Each layer-three JSON file contains:

- `id`, `name`, `category`, and `description`
- `documentation_url`
- normalized `auth`, `https`, and `cors` metadata
- an intentionally nullable `request.base_url`
- upstream repository and a semantic entry fingerprint

`base_url` stays null because the source repository lists documentation pages, not endpoint specifications. Supply it in local configuration after checking provider documentation.

## Incremental synchronization

The manifest stores the upstream revision and an ordered semantic catalog digest. Layer-three definitions deliberately exclude the volatile global revision and README line number; they store a fingerprint of only their API metadata. Therefore an upstream insertion changes only the new definition plus affected indexes and the manifest.

If the parsed catalog digest is already current, synchronization exits without rewriting files. Increment `GENERATOR_VERSION` whenever generator formatting or schemas change, or use `--force` for a deliberate full rebuild. The scheduled GitHub workflow validates the full source but commits only Git-detected additions, edits, and deletions under the two generated layers.

## Synchronization invariants

- Every parsed upstream row produces exactly one JSON definition.
- Every manifest entry points to an existing definition.
- Every definition is referenced exactly once by the manifest.
- IDs and output paths are unique and deterministic for the same source.
- Unchanged semantic API entries produce byte-identical layer-three files across upstream revisions and line-number shifts.
- No secret or local runtime configuration is generated into the skill.
