from __future__ import annotations

import argparse
import os
from unittest import mock
import unittest

from api_client import ClientError, ProxySettings, RequestSpec, build_request, execute


def request_args(**overrides):
    values = {
        "url": None,
        "path": "/v1/items",
        "method": "GET",
        "header": [],
        "query": ["limit=10"],
        "json_data": None,
        "data": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class ClientTests(unittest.TestCase):
    def test_no_auth_request(self) -> None:
        definition = {
            "id": "test/open",
            "auth": {"type": "none", "strategy": "none", "required": False},
            "request": {"base_url": None},
        }
        config = {"defaults": {"timeout": 5}, "apis": {"test/open": {"base_url": "https://api.example"}}}
        spec, timeout, proxy = build_request(definition, config, request_args())
        self.assertEqual("https://api.example/v1/items?limit=10", spec.final_url())
        self.assertEqual(5.0, timeout)
        self.assertIsNone(proxy)

    def test_api_key_is_injected_and_redacted(self) -> None:
        definition = {
            "id": "test/keyed",
            "auth": {
                "type": "apiKey",
                "strategy": "configurable",
                "required": True,
                "credential_env": "PUBLIC_API_TEST_KEY",
            },
            "request": {"base_url": None},
        }
        config = {
            "defaults": {},
            "apis": {
                "test/keyed": {
                    "base_url": "https://api.example",
                    "auth": {"location": "header", "name": "X-Key"},
                }
            },
        }
        with mock.patch.dict(os.environ, {"PUBLIC_API_TEST_KEY": "secret"}, clear=False):
            spec, _, _ = build_request(definition, config, request_args())
        self.assertEqual("secret", spec.headers["X-Key"])
        self.assertEqual("***", spec.visible_headers()["X-Key"])

    def test_generic_key_requires_location(self) -> None:
        definition = {
            "id": "test/keyed",
            "auth": {
                "type": "apiKey",
                "strategy": "configurable",
                "required": True,
                "credential_env": "PUBLIC_API_TEST_KEY",
            },
            "request": {"base_url": None},
        }
        config = {"defaults": {}, "apis": {"test/keyed": {"base_url": "https://api.example"}}}
        with mock.patch.dict(os.environ, {"PUBLIC_API_TEST_KEY": "secret"}, clear=False):
            with self.assertRaises(ClientError):
                build_request(definition, config, request_args())

    def test_global_proxy_is_applied_to_both_schemes(self) -> None:
        definition = {
            "id": "test/open",
            "auth": {"type": "none", "strategy": "none", "required": False},
            "request": {"base_url": None},
        }
        config = {
            "defaults": {"proxy": "http://127.0.0.1:7890"},
            "apis": {"test/open": {"base_url": "https://api.example"}},
        }
        _, _, proxy = build_request(definition, config, request_args())
        self.assertEqual(
            {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"},
            proxy.routes,
        )

    def test_api_proxy_overrides_global_proxy_from_environment(self) -> None:
        definition = {
            "id": "test/open",
            "auth": {"type": "none", "strategy": "none", "required": False},
            "request": {"base_url": None},
        }
        config = {
            "defaults": {"proxy": "http://global.example:8080"},
            "apis": {
                "test/open": {
                    "base_url": "https://api.example",
                    "proxy_env": "TEST_PUBLIC_API_PROXY",
                }
            },
        }
        with mock.patch.dict(
            os.environ, {"TEST_PUBLIC_API_PROXY": "http://api.example:3128"}, clear=False
        ):
            _, _, proxy = build_request(definition, config, request_args())
        self.assertEqual("http://api.example:3128", proxy.routes["https"])

    def test_execute_uses_configured_proxy_opener(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b'{"ok": true}'
        response.status = 200
        response.headers.items.return_value = []
        opener = mock.MagicMock()
        opener.open.return_value = response
        spec = RequestSpec(url="https://api.example/v1", method="GET")
        proxy = ProxySettings({"https": "http://proxy.example:8080"})
        with mock.patch("api_client.build_opener", return_value=opener) as builder:
            result = execute(spec, 5, proxy)
        builder.assert_called_once()
        opener.open.assert_called_once()
        self.assertEqual({"ok": True}, result["body"])


if __name__ == "__main__":
    unittest.main()
