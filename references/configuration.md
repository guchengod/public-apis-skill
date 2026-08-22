# API configuration

Copy `assets/api-config.example.json` outside the skill and edit only the APIs you use. Pass it with `--config`, set `PUBLIC_API_CONFIG` to its path, or place it at `~/.config/public-api-skill/config.json`.

Prefer environment variables for secrets. Resolution order is: `auth.value` in the API override, the variable named by `auth.value_env`, then the deterministic variable shown by `api_client.py show`. File values are supported for controlled local environments but should never be committed.

When a required API key is missing, follow [API key acquisition](key-acquisition.md). If the Agent has suitable mailbox capability and the user has authorized key acquisition, it may complete a free email-only registration and configure the resulting environment variable. Without mailbox capability, it must provide the official signup steps and ask the user to register.

Each API override supports:

```json
{
  "base_url": "https://api.provider.example",
  "auth": {
    "location": "header",
    "name": "X-API-Key",
    "scheme": null,
    "value_env": "PROVIDER_API_KEY"
  }
}
```

`location` can be `header` or `query`. OAuth defaults to the `Authorization` header with the `Bearer` scheme. Generic `apiKey` entries deliberately require a configured location and name because the upstream catalog does not specify them.

Use `--url` for a one-off absolute endpoint or configure `base_url` and use `--path`. Query arguments use repeated `--query key=value`; headers use repeated `--header name=value`. `--dry-run` redacts credential values.

## Proxy

Set a proxy under `defaults` to route every API request through it:

```json
{
  "defaults": {
    "proxy": "http://127.0.0.1:7890"
  }
}
```

A string applies to both HTTP and HTTPS targets. Use separate routes when required:

```json
{
  "defaults": {
    "proxy": {
      "http": "http://proxy.example:8080",
      "https": "http://proxy.example:8080"
    }
  }
}
```

Put proxy URLs containing credentials in an environment variable instead of JSON:

```json
{
  "defaults": {
    "proxy_env": "PUBLIC_API_PROXY"
  }
}
```

The same `proxy` or `proxy_env` fields can be placed inside one `apis.<id>` override; the API-specific value takes priority over the global default. Set an API's `proxy` to `false` to force that API to connect directly. Without explicit proxy configuration, Python's standard `HTTP_PROXY`, `HTTPS_PROXY`, and `NO_PROXY` behavior remains available. Dry-run output reports only whether proxying is enabled and its target schemes; it never prints proxy URLs or embedded credentials.

The client uses Python's standard library, has a configurable timeout, and emits provider responses without inventing a response schema.
