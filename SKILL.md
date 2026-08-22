---
name: public-api-skill
description: Discover, inspect, configure, and call APIs from the public-apis/public-apis catalog. Use when choosing a public API, checking its authentication/HTTPS/CORS metadata, or making a configured HTTP request to a listed service.
---

# Public API Catalog

Use this skill as a three-layer interface:

1. This file explains routing and safe operation.
2. [The catalog](references/catalog/INDEX.md) groups every upstream entry by category. Read only the relevant category page; use `scripts/api_client.py list` for programmatic search.
3. Each category page links to one JSON interface definition under `references/apis/`. Load only the selected definitions.

## Workflow

1. Search before choosing: `python3 scripts/api_client.py list --search "<need>"`.
2. Inspect a candidate: `python3 scripts/api_client.py show <category/api-id>`.
3. Follow its `documentation_url` to learn provider-specific paths and parameters. The upstream catalog does not publish endpoint specifications, so never treat a documentation URL as a base URL.
4. For authenticated, proxied, or callable requests, read [configuration](references/configuration.md), create a local config, and put secrets in environment variables.
5. Preview authentication and URL assembly with `request ... --dry-run`, then remove `--dry-run` only when the target, method, and parameters are correct.

Do not claim an API is currently available from catalog metadata alone. `https` and `cors` describe upstream catalog claims and may be `unknown`.

## Commands

```bash
python3 scripts/api_client.py list --category Animals --auth apiKey
python3 scripts/api_client.py show animals/adoptapet
python3 scripts/api_client.py request animals/adoptapet --path /v1/pets --query limit=10 --dry-run
python3 scripts/sync_catalog.py --source /path/to/public-apis/README.md
python3 scripts/validate_catalog.py
```

Run synchronization only when the user asks to refresh or modify the catalog. It rebuilds generated layer-two and layer-three files transactionally. See [architecture](references/architecture.md) when maintaining the parser, generator, schemas, or authentication strategies.

The repository workflow `.github/workflows/sync-public-apis.yml` checks upstream daily and opens or updates an automated pull request only when the semantic catalog changes.
