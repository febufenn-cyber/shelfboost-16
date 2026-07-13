from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from .common import canonical_shop_domain

DEFAULT_API_VERSION = "2026-07"

PRODUCTS_QUERY = """
query ShelfboostProducts($first: Int!, $after: String, $query: String) {
  products(first: $first, after: $after, query: $query, sortKey: UPDATED_AT) {
    nodes {
      id
      legacyResourceId
      handle
      title
      descriptionHtml
      vendor
      productType
      status
      tags
      createdAt
      updatedAt
      seo { title description }
      metafields(first: 50, namespace: "facts") {
        nodes { namespace key type value }
        pageInfo { hasNextPage }
      }
      variants(first: 100) {
        nodes {
          id
          legacyResourceId
          title
          sku
          barcode
          price
          selectedOptions { name value }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

PRODUCT_QUERY = """
query ShelfboostProduct($id: ID!) {
  product(id: $id) {
    id
    legacyResourceId
    handle
    title
    descriptionHtml
    vendor
    productType
    status
    tags
    createdAt
    updatedAt
    seo { title description }
    metafields(first: 50, namespace: "facts") {
      nodes { namespace key type value }
      pageInfo { hasNextPage }
    }
    variants(first: 100) {
      nodes {
        id
        legacyResourceId
        title
        sku
        barcode
        price
        selectedOptions { name value }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""

VARIANTS_QUERY = """
query ShelfboostVariants($id: ID!, $first: Int!, $after: String) {
  product(id: $id) {
    variants(first: $first, after: $after) {
      nodes {
        id
        legacyResourceId
        title
        sku
        barcode
        price
        selectedOptions { name value }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""


class ShopifyError(RuntimeError):
    pass


class VersionMismatch(ShopifyError):
    pass


@dataclass(frozen=True)
class TransportResponse:
    status: int
    headers: dict[str, str]
    body: bytes


class Transport(Protocol):
    def post(self, url: str, headers: dict[str, str], body: bytes, timeout: float) -> TransportResponse:
        ...


class UrllibTransport:
    def post(self, url: str, headers: dict[str, str], body: bytes, timeout: float) -> TransportResponse:
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return TransportResponse(
                    status=response.status,
                    headers={key.lower(): value for key, value in response.headers.items()},
                    body=response.read(),
                )
        except urllib.error.HTTPError as exc:
            return TransportResponse(
                status=exc.code,
                headers={key.lower(): value for key, value in exc.headers.items()},
                body=exc.read(),
            )


@dataclass
class GraphQLResult:
    data: dict[str, Any]
    raw_payload: dict[str, Any]
    api_version: str
    attempts: int


class ShopifyGraphQLClient:
    def __init__(
        self,
        shop_domain: str,
        access_token: str,
        api_version: str = DEFAULT_API_VERSION,
        *,
        transport: Transport | None = None,
        timeout: float = 30.0,
        max_attempts: int = 4,
        sleep=time.sleep,
    ) -> None:
        self.shop_domain = canonical_shop_domain(shop_domain)
        if not access_token.strip():
            raise ValueError("Shopify access token is empty")
        self.access_token = access_token.strip()
        self.api_version = api_version.strip()
        self.transport = transport or UrllibTransport()
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.sleep = sleep
        self.request_count = 0

    @property
    def endpoint(self) -> str:
        return f"https://{self.shop_domain}/admin/api/{self.api_version}/graphql.json"

    def execute(self, query: str, variables: dict[str, Any]) -> GraphQLResult:
        payload = json.dumps({"query": query, "variables": variables}, separators=(",", ":")).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Shopify-Access-Token": self.access_token,
            "User-Agent": "Shelfboost-Phase2/0.1",
        }
        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            self.request_count += 1
            try:
                response = self.transport.post(self.endpoint, headers, payload, self.timeout)
            except OSError as exc:
                last_error = f"transport_error:{exc}"
                if attempt == self.max_attempts:
                    break
                self.sleep(min(8.0, 0.5 * (2 ** (attempt - 1))))
                continue

            observed = response.headers.get("x-shopify-api-version", "")
            if observed and observed != self.api_version:
                raise VersionMismatch(
                    f"Requested Shopify API {self.api_version}, but response used {observed}"
                )

            if response.status == 429 or 500 <= response.status <= 599:
                last_error = f"http_{response.status}:{response.body[:300].decode('utf-8', 'replace')}"
                if attempt == self.max_attempts:
                    break
                retry_after = response.headers.get("retry-after", "")
                try:
                    delay = float(retry_after)
                except ValueError:
                    delay = min(8.0, 0.5 * (2 ** (attempt - 1)))
                self.sleep(max(0.0, delay))
                continue

            if response.status < 200 or response.status >= 300:
                raise ShopifyError(
                    f"Shopify returned HTTP {response.status}: {response.body[:500].decode('utf-8', 'replace')}"
                )

            try:
                decoded = json.loads(response.body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ShopifyError(f"Shopify returned invalid JSON: {exc}") from exc
            if decoded.get("errors"):
                raise ShopifyError("GraphQL errors: " + json.dumps(decoded["errors"], ensure_ascii=False))
            data = decoded.get("data")
            if not isinstance(data, dict):
                raise ShopifyError("GraphQL response does not contain a data object")
            return GraphQLResult(data=data, raw_payload=decoded, api_version=observed or self.api_version, attempts=attempt)

        raise ShopifyError(f"Shopify request failed after {self.max_attempts} attempts: {last_error}")

    def iter_products(self, *, page_size: int = 50, since: str = ""):
        after: str | None = None
        page_number = 0
        query_filter = f"updated_at:>'{since}'" if since else None
        while True:
            page_number += 1
            result = self.execute(
                PRODUCTS_QUERY,
                {"first": page_size, "after": after, "query": query_filter},
            )
            connection = result.data["products"]
            yield page_number, after or "", result, connection
            page_info = connection["pageInfo"]
            if not page_info["hasNextPage"]:
                break
            after = page_info["endCursor"]
            if not after:
                raise ShopifyError("Products page indicated hasNextPage without endCursor")

    def fetch_product(self, product_gid: str) -> GraphQLResult:
        return self.execute(PRODUCT_QUERY, {"id": product_gid})

    def fetch_remaining_variants(self, product_gid: str, after: str, *, page_size: int = 100):
        page_number = 0
        cursor: str | None = after
        while cursor:
            page_number += 1
            result = self.execute(
                VARIANTS_QUERY,
                {"id": product_gid, "first": page_size, "after": cursor},
            )
            product = result.data.get("product")
            if not product:
                raise ShopifyError(f"Product disappeared while paginating variants: {product_gid}")
            connection = product["variants"]
            yield page_number, cursor, result, connection
            info = connection["pageInfo"]
            if not info["hasNextPage"]:
                break
            cursor = info["endCursor"]
            if not cursor:
                raise ShopifyError("Variants page indicated hasNextPage without endCursor")
