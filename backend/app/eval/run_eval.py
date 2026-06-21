"""Run duplicate-retrieval evaluation via the shared ``relevance_eval`` skill.

This wires the existing similar-article service into the skill's injected-search
contract (see :mod:`app.eval.skill_adapter`) and scores duplicate detection with
Precision@k / MRR@k / nDCG@k per signal strategy, writing a JSON + Markdown
report and gating against a thresholds file.

It needs a LIVE Elasticsearch backend (it builds the real similarity service), so
it is an integration / run-locally tool, not part of the offline test gate. The
offline unit tests in ``tests/test_eval_skill_integration.py`` exercise the same
adapter + skill path with fakes.

Usage::

    cd backend && .venv/bin/python -m app.eval.run_eval \
        --judgments app/eval/judgments.example.json \
        --thresholds app/eval/thresholds.example.json \
        --output-dir reports

Exits non-zero if the threshold gate fails.

The skill is an optional dependency; install it with::

    pip install -e "backend/.[eval]"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.eval.skill_adapter import STRATEGY_FLAGS, make_search_fn

DEFAULT_JUDGMENTS = "app/eval/judgments.example.json"
DEFAULT_THRESHOLDS = "app/eval/thresholds.example.json"
DEFAULT_OUTPUT_DIR = "reports"
DEFAULT_KS = (1, 3, 5, 10)


def _load_judgments(path: str) -> dict:
    import json

    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--judgments", default=DEFAULT_JUDGMENTS)
    parser.add_argument("--thresholds", default=DEFAULT_THRESHOLDS)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--strategies",
        nargs="+",
        default=sorted(STRATEGY_FLAGS),
        help=f"Strategies to evaluate (default: all known: {sorted(STRATEGY_FLAGS)}).",
    )
    args = parser.parse_args(argv)

    # Imported lazily so the module imports even when the optional skill / live ES
    # deps are absent (e.g. when only the offline adapter tests are collected).
    from relevance_eval import (
        evaluate_thresholds,
        load_thresholds,
        run_evaluation,
        to_json,
        to_markdown,
    )

    from app.similarity.service import build_similarity_service

    judgments = _load_judgments(args.judgments)
    thresholds = load_thresholds(args.thresholds)

    service = build_similarity_service()
    search_fn = make_search_fn(service)

    report = run_evaluation(judgments, search_fn, args.strategies, ks=DEFAULT_KS)
    gate = evaluate_thresholds(report, thresholds)

    markdown = to_markdown(report, gate, title="Duplicate-retrieval evaluation")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "duplicate_eval.json").write_text(to_json(report), encoding="utf-8")
    (output_dir / "duplicate_eval.md").write_text(markdown, encoding="utf-8")

    print(markdown)
    return 0 if gate["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
