from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

from app.config import EffectiveConfig, HealthResponse, get_effective_config


router = APIRouter()


def env_flag(name: str) -> bool:
    return os.getenv(name, "false").lower() in {"1", "true", "yes", "on"}


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(service="backend", status="ok")


@router.get("/config/effective", response_model=EffectiveConfig, tags=["system"])
def config_effective() -> EffectiveConfig:
    if not env_flag("ENABLE_DEBUG_CONFIG_ENDPOINT"):
        raise HTTPException(status_code=404)
    return get_effective_config()

