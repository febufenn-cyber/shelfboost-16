from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any

HTML_TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def clean_text(value: str | None) -> str:
    raw = html.unescape(value or "")
    return SPACE_RE.sub(" ", HTML_TAG_RE.sub(" ", raw)).strip()


def normalized(value: str | None) -> str:
    text = clean_text(value).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def first_value(row: dict[str, str], *names: str) -> str:
    for name in names:
        if name in row and row[name] is not None:
            return row[name].strip()
    return ""
