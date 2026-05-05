from __future__ import annotations

from typing import Any


def sanitize_text(value: str) -> str:
    # Drop lone surrogate code points so UTF-8 encoding and downstream JSON serialization stay safe.
    return value.encode("utf-8", errors="ignore").decode("utf-8")


def sanitize_jsonish(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, list):
        return [sanitize_jsonish(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_jsonish(item) for item in value]
    if isinstance(value, dict):
        return {
            sanitize_text(str(key)) if not isinstance(key, str) else sanitize_text(key): sanitize_jsonish(item)
            for key, item in value.items()
        }
    return value
