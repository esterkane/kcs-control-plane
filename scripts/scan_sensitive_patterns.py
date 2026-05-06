#!/usr/bin/env python3
"""Emit JSON findings for sensitive strings in tracked text files."""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXCLUDES = {
    ".git/*",
    "node_modules/*",
    "frontend/node_modules/*",
    "backend/.venv/*",
    ".venv/*",
    "scripts/scan_sensitive_patterns.py",
}
MAX_SNIPPET = 160


PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("local_path", re.compile("/" + r"Users/[^\s\"')\]]+"), "P2"),
    ("support_host", re.compile("support" + r"\.elastic\.dev"), "P1"),
    (
        "production_index",
        re.compile(
            r"\b(?:search-knowledge-articles-prod-v\d+|kcs-kb-analysis-[a-z0-9._-]+|"
            r"[a-z0-9._-]*(?:prod|production)[_-][a-z0-9._-]*(?:index|alias|v\d)|"
            r"[a-z0-9._-]*(?:index|alias)[_-][a-z0-9._-]*(?:prod|production)[a-z0-9._-]*)\b",
            re.I,
        ),
        "P1",
    ),
    (
        "api_key_value",
        re.compile(
            r"\b"
            + "api"
            + r"[_-]?key\b\s*[:=]\s*[\"']"
            + r"(?!(?:secret|source-key|test|example|placeholder|changeme|<[^>]+>)[\"'])"
            + r"[A-Za-z0-9][A-Za-z0-9._~+/=-]{15,}[\"']",
            re.I,
        ),
        "P1",
    ),
    ("api_key_reference", re.compile(r"\b" + "api" + r"[_-]?key\b", re.I), "P2"),
    ("bearer_token", re.compile(r"\b" + "Bearer" + r"\s+[A-Za-z0-9._~+/=-]{8,}"), "P0"),
    (
        "slack_webhook",
        re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9_/+-]+"),
        "P0",
    ),
    (
        "rfc1918_ip",
        re.compile(
            r"\b(?:10(?:\.\d{1,3}){3}|172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2}|"
            r"192\.168(?:\.\d{1,3}){2})\b"
        ),
        "P1",
    ),
    (
        "internal_email",
        re.compile(r"\b[A-Z0-9._%+-]+@(?:elastic\.co|elastic\.com)\b", re.I),
        "P1",
    ),
]


def split_env_list(value: str | None) -> list[str]:
    if not value:
        return []
    normalized = value.replace(os.pathsep, ",").replace("\n", ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [REPO_ROOT / line for line in result.stdout.splitlines() if line]


def selected_paths(paths: list[str], files: list[Path]) -> set[Path]:
    if not paths:
        return set(files)

    selected: set[Path] = set()
    for raw_path in paths:
        candidate = (REPO_ROOT / raw_path).resolve()
        matches = [
            file_path
            for file_path in files
            if file_path == candidate
            or candidate in file_path.parents
            or fnmatch.fnmatch(file_path.relative_to(REPO_ROOT).as_posix(), raw_path)
        ]
        selected.update(matches)
    return selected


def is_excluded(path: Path, patterns: set[str]) -> bool:
    relative = path.relative_to(REPO_ROOT).as_posix()
    return any(fnmatch.fnmatch(relative, pattern) for pattern in patterns)


def read_text(path: Path) -> str | None:
    data = path.read_bytes()
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return None


def snippet(line: str) -> str:
    collapsed = " ".join(line.strip().split())
    if len(collapsed) <= MAX_SNIPPET:
        return collapsed
    return collapsed[: MAX_SNIPPET - 3] + "..."


def scan_file(path: Path) -> list[dict[str, object]]:
    text = read_text(path)
    if text is None:
        return []

    findings: list[dict[str, object]] = []
    relative = path.relative_to(REPO_ROOT).as_posix()
    for line_number, line in enumerate(text.splitlines(), start=1):
        for pattern_name, regex, risk in PATTERNS:
            if regex.search(line):
                findings.append(
                    {
                        "file": relative,
                        "line": line_number,
                        "snippet": snippet(line),
                        "risk": risk,
                        "pattern": pattern_name,
                    }
                )
    return findings


def main() -> int:
    excludes = DEFAULT_EXCLUDES | set(split_env_list(os.environ.get("EXCLUDE_GLOBS")))
    files = sorted(selected_paths(split_env_list(os.environ.get("PATHS")), tracked_files()))
    findings: list[dict[str, object]] = []
    for path in files:
        if path.is_file() and not is_excluded(path, excludes):
            findings.extend(scan_file(path))

    print(json.dumps(findings, indent=2))
    return 1 if any(finding["risk"] in {"P0", "P1"} for finding in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
