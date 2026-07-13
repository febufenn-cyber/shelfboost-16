from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from shelfboost_phase2.common import json_dumps, sha256_bytes

PRODUCT_UPDATE_MUTATION = """
mutation ShelfboostProductUpdate($product: ProductUpdateInput!) {
  productUpdate(product: $product) {
    product {
      id
      handle
      descriptionHtml
      updatedAt
      seo { title description }
    }
    userErrors { field message }
  }
}
"""


class MutationUncertain(RuntimeError):
    """The request may have reached Shopify; reconcile before another write."""


class MutationRejected(RuntimeError):
    pass


@dataclass(frozen=True)
class UpdateResult:
    product: dict[str, Any]
    user_errors: list[dict[str, Any]]
    raw_payload: dict[str, Any]
    request_payload: dict[str, Any]


class SafeShopifyProductWriter:
    """Single-attempt mutation adapter around the Phase 2 Shopify client."""

    def __init__(self, client: Any) -> None:
        self.client = client

    @property
    def shop_domain(self) -> str:
        return self.client.shop_domain

    def fetch(self, product_gid: str) -> dict[str, Any] | None:
        result = self.client.fetch_product(product_gid)
        product = result.data.get("product")
        return product if isinstance(product, dict) else None

    def update_once(
        self,
        product_gid: str,
        proposed_fields: dict[str, str],
        changed_fields: list[str],
    ) -> UpdateResult:
        product_input: dict[str, Any] = {"id": product_gid}
        if "Body (HTML)" in changed_fields:
            product_input["descriptionHtml"] = proposed_fields["Body (HTML)"]
        seo: dict[str, str] = {}
        if "SEO Title" in changed_fields:
            seo["title"] = proposed_fields["SEO Title"]
        if "SEO Description" in changed_fields:
            seo["description"] = proposed_fields["SEO Description"]
        if seo:
            product_input["seo"] = seo
        request_payload = {
            "query": PRODUCT_UPDATE_MUTATION,
            "variables": {"product": product_input},
        }
        encoded = json.dumps(request_payload, separators=(",", ":")).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Shopify-Access-Token": self.client.access_token,
            "User-Agent": "Shelfboost-Phase3/0.2",
        }
        try:
            response = self.client.transport.post(
                self.client.endpoint,
                headers,
                encoded,
                self.client.timeout,
            )
        except OSError as exc:
            raise MutationUncertain(f"transport_error:{exc}") from exc

        observed = response.headers.get("x-shopify-api-version", "")
        if observed and observed != self.client.api_version:
            raise MutationRejected(
                f"Requested Shopify API {self.client.api_version}, but response used {observed}"
            )
        if response.status == 429:
            raise MutationUncertain("safe_retry:http_429")
        if 500 <= response.status <= 599:
            raise MutationUncertain(
                f"http_{response.status}:{response.body[:300].decode('utf-8', 'replace')}"
            )
        if response.status < 200 or response.status >= 300:
            raise MutationRejected(
                f"Shopify returned HTTP {response.status}: "
                f"{response.body[:500].decode('utf-8', 'replace')}"
            )
        try:
            decoded = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MutationUncertain(f"invalid_success_response:{exc}") from exc
        if decoded.get("errors"):
            raise MutationUncertain(
                "GraphQL top-level errors: " + json_dumps(decoded["errors"])
            )
        payload = (decoded.get("data") or {}).get("productUpdate")
        if not isinstance(payload, dict):
            raise MutationUncertain("Mutation response omitted productUpdate")
        user_errors = payload.get("userErrors") or []
        product = payload.get("product")
        if user_errors:
            return UpdateResult(
                product=product if isinstance(product, dict) else {},
                user_errors=list(user_errors),
                raw_payload=decoded,
                request_payload=request_payload,
            )
        if not isinstance(product, dict):
            raise MutationUncertain(
                "Mutation succeeded without returning the updated product"
            )
        return UpdateResult(
            product=product,
            user_errors=[],
            raw_payload=decoded,
            request_payload=request_payload,
        )


def payload_digest(payload: dict[str, Any]) -> str:
    return sha256_bytes(json_dumps(payload).encode("utf-8"))
