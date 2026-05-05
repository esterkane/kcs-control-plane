from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.admin import router as admin_router
from app.api.routes.clusters import router as clusters_router
from app.api.routes.kb import router as kb_router
from app.api.routes.system import router as system_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="kcs-control-plane-backend",
        version="0.1.0",
        summary="FastAPI bootstrap for the KB control plane.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(system_router)
    app.include_router(admin_router)
    app.include_router(kb_router)
    app.include_router(clusters_router)
    return app


app = create_app()
