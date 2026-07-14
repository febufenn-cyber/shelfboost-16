from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from shelfboost_phase2.shopify import DEFAULT_API_VERSION, ShopifyGraphQLClient

from .audit import build_audit_bundle
from .db import initialize
from .execution import execute_publish
from .planning import plan_publish, publish_status
from .rollback import execute_rollback, plan_rollback
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

    rollback_plan = sub.add_parser("plan-rollback")
    rollback_plan.add_argument("--batch-id", type=int, required=True)

    rollback = sub.add_parser("rollback")
    rollback.add_argument("--shop", required=True)
    rollback.add_argument("--rollback-run-id", type=int, required=True)
    rollback.add_argument("--token-env", default="SHOPIFY_ACCESS_TOKEN")
    rollback.add_argument("--api-version", default=DEFAULT_API_VERSION)
    rollback.add_argument("--limit", type=int, default=25)

    audit = sub.add_parser("audit-bundle")
    audit.add_argument("--batch-id", type=int, required=True)

    sub.add_parser("status")
    return parser


def _writer(args) -> SafeShopifyProductWriter:
    token = os.environ.get(args.token_env, "")
    if not token:
        raise SystemExit(f"Environment variable {args.token_env} is empty")
    return SafeShopifyProductWriter(ShopifyGraphQLClient(args.shop, token, args.api_version))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "init":
        print(initialize(args.workspace))
        return 0
    if args.command == "plan":
        result = plan_publish(
            args.workspace, args.shop, args.approved_csv,
            args.changes_json, args.bridge_manifest,
        )
    elif args.command == "execute":
        result = execute_publish(args.workspace, _writer(args), args.batch_id, limit=args.limit)
    elif args.command == "plan-rollback":
        result = plan_rollback(args.workspace, args.batch_id)
    elif args.command == "rollback":
        result = execute_rollback(
            args.workspace, _writer(args), args.rollback_run_id, limit=args.limit,
        )
    elif args.command == "audit-bundle":
        result = build_audit_bundle(args.workspace, args.batch_id)
    elif args.command == "status":
        result = publish_status(args.workspace)
    else:
        raise AssertionError(args.command)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0
