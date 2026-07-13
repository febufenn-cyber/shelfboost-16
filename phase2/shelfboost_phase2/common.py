from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

SHOP_DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.myshopify\.com$", re.IGNORECASE)


def canonical_shop_domain(value: str) -> str:
    domain = value.strip().lower()
    domain = domain.removeprefix("https://").removeprefix("http://").strip("/")
    if not SHOP_DOMAIN_RE.fullmatch(domain):
        raise ValueError("Shop domain must look like store-name.myshopify.com")
    return domain


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
