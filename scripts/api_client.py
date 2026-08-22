#!/usr/bin/env python3
"""Search, inspect, and call every generated public API interface."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.request import ProxyHandler, Request, build_opener, urlopen


class ClientError(RuntimeError):
    pass


class ApiRegistry:
    """Facade over the layer-two manifest and layer-three definitions."""

    def __init__(self, root: Path):
        self.root = root
        manifest_path = root / "references" / "catalog" / "manifest.json"
        try:
            self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ClientError("catalog is missing; run scripts/sync_catalog.py") from exc
        self._entries = {item["id"]: item for item in self.manifest["entries"]}

    def list(
        self,
        *,
        category: str | None = None,
        auth: str | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        results = []
        needle = search.casefold() if search else None
        for item in self.manifest["entries"]:
            if category and item["category"].casefold() != category.casefold():
                continue
            if auth and item["auth"].casefold() != auth.casefold():
                continue
            haystack = " ".join(
                (item["id"], item["name"], item["category"], item["description"])
            ).casefold()
            if needle and needle not in haystack:
                continue
            results.append(item)
        return results

    def get(self, api_id: str) -> dict[str, Any]:
        item = self._entries.get(api_id)
        if item is None:
            matches = [candidate for candidate in self._entries if candidate.endswith(f"/{api_id}")]
            if len(matches) == 1:
                item = self._entries[matches[0]]
            else:
                raise ClientError(f"unknown or ambiguous API id: {api_id}")
        path = self.root / item["definition"]
        return json.loads(path.read_text(encoding="utf-8"))


class ConfigurationProvider:
    def load(self) -> dict[str, Any] | None:
        raise NotImplementedError


class ExplicitConfiguration(ConfigurationProvider):
    def __init__(self, path: Path | None):
        self.path = path

    def load(self) -> dict[str, Any] | None:
        return _read_config(self.path) if self.path else None


class EnvironmentConfiguration(ConfigurationProvider):
    def load(self) -> dict[str, Any] | None:
        value = os.environ.get("PUBLIC_API_CONFIG")
        return _read_config(Path(value).expanduser()) if value else None


class DefaultConfiguration(ConfigurationProvider):
    def load(self) -> dict[str, Any] | None:
        path = Path.home() / ".config" / "public-api-skill" / "config.json"
        return _read_config(path) if path.is_file() else None


def load_configuration(path: Path | None) -> dict[str, Any]:
    """Chain of responsibility: explicit path, environment path, default path."""
    for provider in (
        ExplicitConfiguration(path),
        EnvironmentConfiguration(),
        DefaultConfiguration(),
    ):
        config = provider.load()
        if config is not None:
            return config
    return {"defaults": {}, "apis": {}}


def _read_config(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ClientError(f"configuration file does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ClientError(f"invalid JSON configuration {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ClientError("configuration root must be an object")
    if not isinstance(payload.get("defaults", {}), dict) or not isinstance(
        payload.get("apis", {}), dict
    ):
        raise ClientError("configuration defaults and apis must be objects")
    return payload


@dataclass
class RequestSpec:
    url: str
    method: str
    headers: dict[str, str] = field(default_factory=dict)
    query: list[tuple[str, str]] = field(default_factory=list)
    body: bytes | None = None
    secret_headers: set[str] = field(default_factory=set)
    secret_queries: set[str] = field(default_factory=set)

    def final_url(self, redact: bool = False) -> str:
        parsed = urlparse(self.url)
        query = parse_qsl(parsed.query, keep_blank_values=True) + self.query
        if redact:
            query = [(key, "***" if key in self.secret_queries else value) for key, value in query]
        return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))

    def visible_headers(self) -> dict[str, str]:
        return {
            key: ("***" if key.casefold() in self.secret_headers else value)
            for key, value in self.headers.items()
        }


@dataclass(frozen=True)
class ProxySettings:
    """Explicit proxy policy; an empty route map disables environment proxies."""

    routes: dict[str, str]

    def visible_summary(self) -> dict[str, Any]:
        return {
            "configured": True,
            "enabled": bool(self.routes),
            "schemes": sorted(self.routes),
        }


def resolve_proxy(
    defaults: Mapping[str, Any], overrides: Mapping[str, Any]
) -> ProxySettings | None:
    """Resolve per-API proxy settings before global defaults."""
    source: Mapping[str, Any] | None = None
    if "proxy" in overrides or "proxy_env" in overrides:
        source = overrides
    elif "proxy" in defaults or "proxy_env" in defaults:
        source = defaults
    if source is None:
        return None

    value = source.get("proxy")
    env_name = source.get("proxy_env")
    if env_name is not None:
        if not isinstance(env_name, str) or not env_name:
            raise ClientError("proxy_env must be a non-empty string")
        env_value = os.environ.get(env_name)
        if env_value is None:
            raise ClientError(f"configured proxy environment variable is missing: {env_name}")
        value = env_value

    if value is None or value is False:
        return ProxySettings({})
    if isinstance(value, str):
        routes = {"http": value, "https": value}
    elif isinstance(value, dict):
        unsupported = set(value) - {"http", "https"}
        if unsupported:
            raise ClientError(
                f"proxy object supports only http/https keys: {sorted(unsupported)}"
            )
        routes = dict(value)
    else:
        raise ClientError("proxy must be a URL string, an http/https object, false, or null")

    for scheme, proxy_url in routes.items():
        if not isinstance(proxy_url, str):
            raise ClientError(f"proxy.{scheme} must be a URL string")
        parsed = urlparse(proxy_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ClientError(f"proxy.{scheme} must be an absolute HTTP(S) URL")
    return ProxySettings(routes)


def resolve_credential(auth: Mapping[str, Any], override: Mapping[str, Any]) -> str | None:
    if "value" in override:
        value = override["value"]
        if not isinstance(value, str):
            raise ClientError("auth.value must be a string")
        return value
    env_name = override.get("value_env") or auth.get("credential_env")
    if env_name:
        if not isinstance(env_name, str):
            raise ClientError("auth.value_env must be a string")
        return os.environ.get(env_name)
    return None


class AuthenticationStrategy:
    def apply(
        self,
        spec: RequestSpec,
        descriptor: Mapping[str, Any],
        override: Mapping[str, Any],
        defaults: Mapping[str, Any],
    ) -> None:
        raise NotImplementedError


class NoAuthentication(AuthenticationStrategy):
    def apply(self, spec: RequestSpec, descriptor: Mapping[str, Any], override: Mapping[str, Any], defaults: Mapping[str, Any]) -> None:
        return


class HeaderOrQueryAuthentication(AuthenticationStrategy):
    def apply(self, spec: RequestSpec, descriptor: Mapping[str, Any], override: Mapping[str, Any], defaults: Mapping[str, Any]) -> None:
        credential = resolve_credential(descriptor, override)
        if credential is None:
            env_name = override.get("value_env") or descriptor.get("credential_env", "configured environment")
            raise ClientError(f"missing credential; set {env_name}")
        location = override.get("location")
        name = override.get("name") or descriptor.get("header")
        if not location and descriptor.get("strategy") == "header":
            location = "header"
        if location not in {"header", "query"} or not isinstance(name, str) or not name:
            raise ClientError("configure auth.location (header/query) and auth.name for this API")
        scheme = override.get("scheme")
        value = f"{scheme} {credential}" if scheme else credential
        if location == "header":
            spec.headers[name] = value
            spec.secret_headers.add(name.casefold())
        else:
            spec.query.append((name, value))
            spec.secret_queries.add(name)


class BearerAuthentication(AuthenticationStrategy):
    def apply(self, spec: RequestSpec, descriptor: Mapping[str, Any], override: Mapping[str, Any], defaults: Mapping[str, Any]) -> None:
        merged = {"location": "header", "name": "Authorization", "scheme": "Bearer", **override}
        HeaderOrQueryAuthentication().apply(spec, descriptor, merged, defaults)


class UserAgentAuthentication(AuthenticationStrategy):
    def apply(self, spec: RequestSpec, descriptor: Mapping[str, Any], override: Mapping[str, Any], defaults: Mapping[str, Any]) -> None:
        value = resolve_credential(descriptor, override) or defaults.get("user_agent")
        if not isinstance(value, str) or not value:
            raise ClientError("configure a User-Agent value for this API")
        spec.headers["User-Agent"] = value


class AuthenticationFactory:
    @staticmethod
    def create(descriptor: Mapping[str, Any]) -> AuthenticationStrategy:
        strategy = descriptor.get("strategy")
        if strategy == "none":
            return NoAuthentication()
        if strategy == "bearer":
            return BearerAuthentication()
        if descriptor.get("type", "").casefold() == "user-agent":
            return UserAgentAuthentication()
        return HeaderOrQueryAuthentication()


def pairs(values: Iterable[str], label: str) -> list[tuple[str, str]]:
    result = []
    for value in values:
        if "=" not in value:
            raise ClientError(f"{label} must use name=value: {value}")
        key, item = value.split("=", 1)
        if not key:
            raise ClientError(f"{label} name cannot be empty")
        result.append((key, item))
    return result


def build_request(
    definition: Mapping[str, Any],
    config: Mapping[str, Any],
    args: argparse.Namespace,
) -> tuple[RequestSpec, float, ProxySettings | None]:
    overrides = config.get("apis", {}).get(definition["id"], {})
    if not isinstance(overrides, dict):
        raise ClientError(f"configuration for {definition['id']} must be an object")
    defaults = config.get("defaults", {})
    base_url = overrides.get("base_url") or definition.get("request", {}).get("base_url")
    if args.url:
        url = args.url
    elif base_url:
        url = urljoin(str(base_url).rstrip("/") + "/", args.path.lstrip("/"))
    else:
        raise ClientError("configure base_url or pass an absolute --url")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ClientError("request target must be an absolute HTTP(S) URL")

    headers = dict(pairs(args.header, "header"))
    query = pairs(args.query, "query")
    body = None
    if args.json_data is not None:
        try:
            parsed_json = json.loads(args.json_data)
        except json.JSONDecodeError as exc:
            raise ClientError(f"invalid --json value: {exc}") from exc
        body = json.dumps(parsed_json, ensure_ascii=False).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    elif args.data is not None:
        body = args.data.encode("utf-8")

    spec = RequestSpec(url=url, method=args.method.upper(), headers=headers, query=query, body=body)
    auth_descriptor = definition["auth"]
    auth_override = overrides.get("auth", {})
    if not isinstance(auth_override, dict):
        raise ClientError("API auth override must be an object")
    AuthenticationFactory.create(auth_descriptor).apply(
        spec, auth_descriptor, auth_override, defaults
    )
    user_agent = defaults.get("user_agent")
    if isinstance(user_agent, str) and user_agent:
        spec.headers.setdefault("User-Agent", user_agent)
    timeout = overrides.get("timeout", defaults.get("timeout", 30))
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ClientError("timeout must be a positive number")
    return spec, float(timeout), resolve_proxy(defaults, overrides)


def execute(
    spec: RequestSpec,
    timeout: float,
    proxy: ProxySettings | None = None,
) -> dict[str, Any]:
    request = Request(
        spec.final_url(),
        data=spec.body,
        headers=spec.headers,
        method=spec.method,
    )
    try:
        if proxy is None:
            response_context = urlopen(request, timeout=timeout)
        else:
            opener = build_opener(ProxyHandler(proxy.routes))
            response_context = opener.open(request, timeout=timeout)
        with response_context as response:
            body = response.read()
            status = response.status
            headers = dict(response.headers.items())
    except HTTPError as exc:
        body = exc.read()
        status = exc.code
        headers = dict(exc.headers.items())
    except URLError as exc:
        raise ClientError(f"request failed: {exc.reason}") from exc
    charset = "utf-8"
    content_type = headers.get("Content-Type", "")
    if "charset=" in content_type:
        charset = content_type.rsplit("charset=", 1)[1].split(";", 1)[0].strip()
    text = body.decode(charset, errors="replace")
    try:
        content: Any = json.loads(text)
    except json.JSONDecodeError:
        content = text
    return {"status": status, "headers": headers, "body": content}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--config", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="search the catalog")
    list_parser.add_argument("--category")
    list_parser.add_argument("--auth")
    list_parser.add_argument("--search")
    list_parser.add_argument("--json", action="store_true", dest="as_json")

    show_parser = subparsers.add_parser("show", help="show one interface definition")
    show_parser.add_argument("api_id")

    request_parser = subparsers.add_parser("request", help="make a configured HTTP request")
    request_parser.add_argument("api_id")
    target = request_parser.add_mutually_exclusive_group()
    target.add_argument("--url")
    target.add_argument("--path", default="")
    request_parser.add_argument("--method", default="GET")
    request_parser.add_argument("--query", action="append", default=[])
    request_parser.add_argument("--header", action="append", default=[])
    body = request_parser.add_mutually_exclusive_group()
    body.add_argument("--data")
    body.add_argument("--json", dest="json_data")
    request_parser.add_argument("--dry-run", action="store_true")
    return parser


def print_list(items: list[dict[str, Any]], as_json: bool) -> None:
    if as_json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return
    print(f"{len(items)} API(s)")
    for item in items:
        print(f"{item['id']}\t{item['auth']}\t{item['description']}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        registry = ApiRegistry(args.root.resolve())
        if args.command == "list":
            print_list(
                registry.list(category=args.category, auth=args.auth, search=args.search),
                args.as_json,
            )
            return 0
        definition = registry.get(args.api_id)
        if args.command == "show":
            print(json.dumps(definition, ensure_ascii=False, indent=2))
            return 0
        config = load_configuration(args.config)
        spec, timeout, proxy = build_request(definition, config, args)
        if args.dry_run:
            payload = {
                "api_id": definition["id"],
                "method": spec.method,
                "url": spec.final_url(redact=True),
                "headers": spec.visible_headers(),
                "body_bytes": len(spec.body or b""),
                "timeout": timeout,
                "proxy": (
                    proxy.visible_summary()
                    if proxy is not None
                    else {"configured": False, "enabled": None, "schemes": []}
                ),
            }
        else:
            payload = execute(spec, timeout, proxy)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except ClientError as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
