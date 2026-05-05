from __future__ import annotations

from fastapi import APIRouter

from app.config import EffectiveConfig, HealthResponse, get_effective_config


router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(service="backend", status="ok")


@router.get("/config/effective", response_model=EffectiveConfig, tags=["system"])
def config_effective() -> EffectiveConfig:
    return get_effective_config()

