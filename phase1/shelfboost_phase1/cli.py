from __future__ import annotations

import argparse
import json
from pathlib import Path

from .batches import select_batch
from .brand import activate_profile
from .catalog import import_catalog
from .db import initialize
from .exporter import export_approved
from .generation import generate_batch
from .review import apply_decisions, create_review_pack
from .status import workspace_status


def emit(value: dict) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Shelfboost Phase 1 local concierge pilot system")
    root.add_argument("--workspace", type=Path, required=True, help="Private local pilot workspace")
    commands = root.add_subparsers(dest="command", required=True)

    commands.add_parser("init", help="Initialize a private pilot workspace")

    import_cmd = commands.add_parser("import-catalog", help="Import and normalize a Shopify CSV")
    import_cmd.add_argument("csv_path", type=Path)

    brand_cmd = commands.add_parser("brand", help="Activate a versioned brand profile JSON")
    brand_cmd.add_argument("profile_path", type=Path)

    batch_cmd = commands.add_parser("select-batch", help="Select a priority pilot batch")
    batch_cmd.add_argument("--name", required=True)
    batch_cmd.add_argument("--limit", type=int, default=10)
    batch_cmd.add_argument("--include-blocked", action="store_true")

    generation_cmd = commands.add_parser("generate", help="Create controlled deterministic drafts")
    generation_cmd.add_argument(
        "--template-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "category_templates",
    )
    generation_cmd.add_argument("--batch-id", type=int)

    review_cmd = commands.add_parser("review-pack", help="Create static review HTML and decision CSV")
    review_cmd.add_argument("--batch-id", type=int)

    decisions_cmd = commands.add_parser("apply-decisions", help="Import merchant review decisions")
    decisions_cmd.add_argument("decisions_path", type=Path)

    export_cmd = commands.add_parser("export", help="Export only approved, validated changes")
    export_cmd.add_argument("output_path", type=Path)
    export_cmd.add_argument("--batch-id", type=int)

    commands.add_parser("status", help="Show workspace evidence and workflow state")
    return root


def main() -> int:
    args = parser().parse_args()
    if args.command == "init":
        emit({"database": str(initialize(args.workspace)), "workspace": str(args.workspace.resolve())})
    elif args.command == "import-catalog":
        emit(import_catalog(args.workspace, args.csv_path))
    elif args.command == "brand":
        emit(activate_profile(args.workspace, args.profile_path))
    elif args.command == "select-batch":
        emit(select_batch(args.workspace, args.name, args.limit, args.include_blocked))
    elif args.command == "generate":
        emit(generate_batch(args.workspace, args.template_dir, args.batch_id))
    elif args.command == "review-pack":
        emit(create_review_pack(args.workspace, args.batch_id))
    elif args.command == "apply-decisions":
        emit(apply_decisions(args.workspace, args.decisions_path))
    elif args.command == "export":
        emit(export_approved(args.workspace, args.output_path, args.batch_id))
    elif args.command == "status":
        emit(workspace_status(args.workspace))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
