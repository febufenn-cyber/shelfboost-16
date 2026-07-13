import json
import unittest
from types import SimpleNamespace

from shelfboost_phase3.writer import (
    MutationUncertain,
    SafeShopifyProductWriter,
)


class Transport:
    def __init__(self, status=200, payload=None, headers=None, exc=None):
        self.status = status
        self.payload = payload or {}
        self.headers = headers or {"x-shopify-api-version": "2026-07"}
        self.exc = exc
        self.calls = []

    def post(self, url, headers, body, timeout):
        self.calls.append(json.loads(body))
        if self.exc:
            raise self.exc
        return SimpleNamespace(
            status=self.status,
            headers=self.headers,
            body=json.dumps(self.payload).encode(),
        )


class Client:
    shop_domain = "fixture-store.myshopify.com"
    access_token = "token"
    api_version = "2026-07"
    endpoint = "https://fixture/admin/api/2026-07/graphql.json"
    timeout = 30

    def __init__(self, transport):
        self.transport = transport

    def fetch_product(self, gid):
        return SimpleNamespace(data={"product": None})


class WriterTests(unittest.TestCase):
    def test_sends_only_changed_selected_field(self):
        product = {
            "id": "gid://shopify/Product/1",
            "handle": "x",
            "descriptionHtml": "old",
            "updatedAt": "2026",
            "seo": {"title": "new", "description": "meta"},
        }
        transport = Transport(
            payload={"data": {"productUpdate": {"product": product, "userErrors": []}}}
        )
        writer = SafeShopifyProductWriter(Client(transport))
        result = writer.update_once(
            product["id"],
            {"Body (HTML)": "old", "SEO Title": "new", "SEO Description": "meta"},
            ["SEO Title"],
        )
        variables = transport.calls[0]["variables"]["product"]
        self.assertEqual(
            variables,
            {"id": product["id"], "seo": {"title": "new"}},
        )
        self.assertFalse(result.user_errors)

    def test_server_error_is_uncertain(self):
        with self.assertRaises(MutationUncertain):
            SafeShopifyProductWriter(
                Client(Transport(status=500, payload={}))
            ).update_once(
                "gid",
                {"Body (HTML)": "x", "SEO Title": "y", "SEO Description": "z"},
                ["SEO Title"],
            )

    def test_rate_limit_is_reconciled_before_retry(self):
        transport = Transport(status=429, payload={})
        with self.assertRaises(MutationUncertain):
            SafeShopifyProductWriter(Client(transport)).update_once(
                "gid",
                {"Body (HTML)": "x", "SEO Title": "y", "SEO Description": "z"},
                ["SEO Title"],
            )
        self.assertEqual(len(transport.calls), 1)

    def test_user_errors_are_returned_for_item_failure(self):
        payload = {
            "data": {
                "productUpdate": {
                    "product": None,
                    "userErrors": [
                        {"field": ["product"], "message": "bad"}
                    ],
                }
            }
        }
        result = SafeShopifyProductWriter(
            Client(Transport(payload=payload))
        ).update_once(
            "gid",
            {"Body (HTML)": "x", "SEO Title": "y", "SEO Description": "z"},
            ["SEO Title"],
        )
        self.assertEqual(result.user_errors[0]["message"], "bad")


if __name__ == "__main__":
    unittest.main()
