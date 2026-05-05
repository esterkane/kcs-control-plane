from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

from app.config import get_deepsearch_api_key, get_deepsearch_url, is_deepsearch_enabled


@dataclass(frozen=True)
class ResearchResponse:
    status_code: int
    json_body: dict[str, Any] | None = None
    text: str = ""


class ResearchTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> ResearchResponse: ...


class ResearchHelperError(RuntimeError):
    pass


class ResearchHelper(Protocol):
    def research(self, query: str) -> str | None: ...


class HttpxResearchTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> ResearchResponse:
        import httpx

        response = httpx.request(
            method=method,
            url=url,
            headers=headers,
            timeout=20.0,
        )
        try:
            parsed = response.json()
        except json.JSONDecodeError:
            parsed = None
        return ResearchResponse(
            status_code=response.status_code,
            json_body=parsed if isinstance(parsed, dict) else None,
            text=response.text,
        )


class NoopResearchHelper:
    def research(self, query: str) -> str | None:
        return None


class DeepSearchResearchHelper:
    def __init__(
        self,
        *,
        endpoint_url: str,
        api_key: str,
        transport: ResearchTransport | None = None,
    ) -> None:
        self.endpoint_url = endpoint_url
        self.api_key = api_key
        self.transport = transport or HttpxResearchTransport()

    def research(self, query: str) -> str | None:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Basic {self.api_key}"
        separator = "&" if "?" in self.endpoint_url else "?"
        url = f"{self.endpoint_url}{separator}{urlencode({'input': query})}"
        response = self.transport.request("GET", url, headers=headers)
        if response.status_code != 200:
            raise ResearchHelperError(
                f"Unexpected DeepSearch response {response.status_code}: {response.text}"
            )
        if response.json_body:
            return json.dumps(response.json_body, ensure_ascii=True, sort_keys=True)
        if response.text:
            return response.text
        return None


def create_research_helper(
    *,
    transport: ResearchTransport | None = None,
) -> ResearchHelper:
    if not is_deepsearch_enabled():
        return NoopResearchHelper()
    api_key = get_deepsearch_api_key()
    if not api_key:
        return NoopResearchHelper()
    return DeepSearchResearchHelper(
        endpoint_url=get_deepsearch_url(),
        api_key=api_key,
        transport=transport,
    )
