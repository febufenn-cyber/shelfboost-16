from __future__ import annotations

import json
from pathlib import Path

from .common import json_dumps
from .db import connect

REQUIRED_KEYS = {"brand_name", "tone", "prohibited_terms", "regional_language"}


def validate_profile(profile: dict) -> None:
    missing = sorted(REQUIRED_KEYS - set(profile))
    if missing:
        raise ValueError("Brand profile missing required keys: " + ", ".join(missing))
    if not isinstance(profile["tone"], list) or not all(isinstance(item, str) for item in profile["tone"]):
        raise ValueError("tone must be a list of strings")
    if not isinstance(profile["prohibited_terms"], list):
        raise ValueError("prohibited_terms must be a list")


def activate_profile(workspace: Path, profile_path: Path) -> dict:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    validate_profile(profile)
    with connect(workspace) as connection:
        current = connection.execute("SELECT COALESCE(MAX(version), 0) AS version FROM brand_profiles").fetchone()
        version = int(current["version"]) + 1
        connection.execute("UPDATE brand_profiles SET active = 0")
        cursor = connection.execute(
            "INSERT INTO brand_profiles(version, brand_name, profile_json, active) VALUES (?, ?, ?, 1)",
            (version, profile["brand_name"], json_dumps(profile)),
        )
    return {"brand_profile_id": int(cursor.lastrowid), "version": version, "brand_name": profile["brand_name"]}


def active_profile(workspace: Path) -> tuple[int, dict]:
    with connect(workspace) as connection:
        row = connection.execute(
            "SELECT id, profile_json FROM brand_profiles WHERE active = 1 ORDER BY version DESC LIMIT 1"
        ).fetchone()
    if not row:
        raise ValueError("No active brand profile. Run `brand` first.")
    return int(row["id"]), json.loads(row["profile_json"])
