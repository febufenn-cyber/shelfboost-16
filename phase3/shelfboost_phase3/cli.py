from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from shelfboost_phase2.shopify import DEFAULT_API_VERSION, ShopifyGraphQLClient

from .db import initialize
from .execution import execute_publish
from .planning import plan_publish, publish_status
from .writer import SafeShopifyProductWriter


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

    execute = sub.add_parser("execute")
    execute.add_argument("--shop", required=True)
    execute.add_argument("--batch-id", type=int, required=True)
    execute.add_argument("--token-env", default="SHOPIFY_ACCESS_TOKEN")
    execute.add_argument("--api-version", default=DEFAULT_API_VERSION)
    execute.add_argument("--limit", type=int, default=25)

    sub.add_parser("status")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "init":
        print(initialize(args.workspace))
        return 0
    if args.command == "plan":
        print(
            json.dumps(
                plan_publish(
                    args.workspace,
                    args.shop,
                    args.approved_csv,
                    args.changes_json,
                    args.bridge_manifest,
                ),
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    if args.command == "execute":
        token = os.environ.get(args.token_env, "")
        if not token:
            raise SystemExit(f"Environment variable {args.token_env} is empty")
        client = ShopifyGraphQLClient(args.shop, token, args.api_version)
        print(
            json.dumps(
                execute_publish(
                    args.workspace,
                    SafeShopifyProductWriter(client),
                    args.batch_id,
                    limit=args.limit,
                ),
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    if args.command == "status":
        print(json.dumps(publish_status(args.workspace), indent=2, ensure_ascii=False))
        return 0
    raise AssertionError(args.command)
