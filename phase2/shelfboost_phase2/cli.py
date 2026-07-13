from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .db import initialize
from .fixture import FixtureTransport
from .shopify import DEFAULT_API_VERSION, ShopifyGraphQLClient
from .sync import sync_catalog, sync_status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Shelfboost Phase 2 read-only Shopify sync")
    parser.add_argument("--workspace", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init")

    sync = sub.add_parser("sync")
    sync.add_argument("--shop", required=True)
    sync.add_argument("--token-env", default="SHOPIFY_ACCESS_TOKEN")
    sync.add_argument("--api-version", default=DEFAULT_API_VERSION)
    sync.add_argument("--mode", choices=("full", "incremental"), default="full")
    sync.add_argument("--since", default="")
    sync.add_argument("--page-size", type=int, default=50)

    fixture = sub.add_parser("sync-fixture")
    fixture.add_argument("--shop", default="fixture-store.myshopify.com")
    fixture.add_argument("--fixture-dir", type=Path, required=True)
    fixture.add_argument("--api-version", default=DEFAULT_API_VERSION)
    fixture.add_argument("--mode", choices=("full", "incremental"), default="full")
    fixture.add_argument("--since", default="")
    fixture.add_argument("--page-size", type=int, default=50)

    sub.add_parser("status")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "init":
        print(initialize(args.workspace))
        return 0
    if args.command == "status":
        print(json.dumps(sync_status(args.workspace), indent=2, ensure_ascii=False))
        return 0
    if args.command == "sync":
        token = os.environ.get(args.token_env, "")
        if not token:
            raise SystemExit(f"Environment variable {args.token_env} is empty")
        client = ShopifyGraphQLClient(args.shop, token, args.api_version)
        result = sync_catalog(
            args.workspace,
            client,
            mode=args.mode,
            since=args.since,
            page_size=args.page_size,
            token_reference=args.token_env,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "sync-fixture":
        transport = FixtureTransport.from_directory(args.fixture_dir)
        client = ShopifyGraphQLClient(args.shop, "fixture-token", args.api_version, transport=transport, sleep=lambda _: None)
        result = sync_catalog(
            args.workspace,
            client,
            mode=args.mode,
            since=args.since,
            page_size=args.page_size,
            token_reference="fixture",
        )
        print(json.dumps(result, indent=2))
        return 0
    raise AssertionError(args.command)
