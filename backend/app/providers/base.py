from __future__ import annotations

from typing import Protocol


class EmbeddingsProvider(Protocol):
    provider_name: str


class RerankerProvider(Protocol):
    provider_name: str


class ExplanationProvider(Protocol):
    provider_name: str

