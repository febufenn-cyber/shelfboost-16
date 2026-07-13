from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from .shopify import TransportResponse


@dataclass
class FixtureItem:
    status: int
    headers: dict[str, str]
    payload: dict


class FixtureTransport:
    """Deterministic transport used by tests and the synthetic demo."""

    def __init__(self, items: list[FixtureItem]) -> None:
        self.items = deque(items)
        self.requests: list[dict] = []

    @classmethod
    def from_directory(cls, directory: Path) -> "FixtureTransport":
        items: list[FixtureItem] = []
        for path in sorted(directory.glob("*.json")):
            wrapper = json.loads(path.read_text(encoding="utf-8"))
            items.append(
                FixtureItem(
                    status=int(wrapper.get("status", 200)),
                    headers={str(k).lower(): str(v) for k, v in wrapper.get("headers", {}).items()},
                    payload=wrapper["payload"],
                )
            )
        if not items:
            raise ValueError(f"No fixture JSON files found in {directory}")
        return cls(items)

    def post(self, url: str, headers: dict[str, str], body: bytes, timeout: float) -> TransportResponse:
        self.requests.append({"url": url, "headers": headers, "body": json.loads(body), "timeout": timeout})
        if not self.items:
            raise AssertionError("Fixture transport received more requests than fixtures")
        item = self.items.popleft()
        return TransportResponse(
            status=item.status,
            headers=item.headers,
            body=json.dumps(item.payload).encode("utf-8"),
        )
