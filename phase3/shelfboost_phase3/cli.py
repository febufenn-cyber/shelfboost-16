from __future__ import annotations

import argparse
import json
from pathlib import Path

from .db import initialize
from .planning import plan_publish, publish_status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Shelfboost Phase 3 reversible publishing")
    parser.add_argument("--workspace", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    plan = sub.add_parser("plan")
    plan.add_argument("--shop", required=True)
    plan.add_argument("--approved-csv", type=Path, required=True)
    plan.add_argument("--changes-json", type=Path, required=True)
    plan.add_argument("--bridge-manifest", type=Path, required=True)
    sub.add_parser("status")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "init":
        print(initialize(args.workspace))
        return 0
    if args.command == "plan":
        result = plan_publish(
            args.workspace,
            args.shop,
            args.approved_csv,
            args.changes_json,
            args.bridge_manifest,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if args.command == "status":
        print(json.dumps(publish_status(args.workspace), indent=2, ensure_ascii=False))
        return 0
    raise AssertionError(args.command)
