from __future__ import annotations

import argparse
import json
from typing import Sequence

from app.ingestion.kb import ingest_kb_articles


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.ingest_kb",
        description="Ingest KB source documents from a remote Elasticsearch index.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Run a full ingestion into the normalized target index.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.full:
        parser.error("the following arguments are required: --full")

    summary = ingest_kb_articles(full=True)
    print(summary.model_dump_json(by_alias=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

