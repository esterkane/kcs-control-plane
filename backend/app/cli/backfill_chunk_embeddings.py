from __future__ import annotations

import argparse
import json
from typing import Sequence

from app.backfill.duplicate_embeddings import backfill_chunk_embeddings_from_env


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="python -m app.cli.backfill_chunk_embeddings",
        description="Backfill duplicate-comparison embeddings on structure-aware article chunks.",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    stats = backfill_chunk_embeddings_from_env()
    print(json.dumps(stats.__dict__, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
