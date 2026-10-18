import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pci.problems.router import router as problems_router
from pci.productions.router import router as productions_router
from pci.routers.internal_contributions import router as internal_contributions_router
from pci.routers.public_contributions import router as public_contributions_router


def create_app() -> FastAPI:
    app = FastAPI(title="ObservAInova", version="0.1.0")
    origins = [
        origin.strip()
        for origin in os.getenv("FRONTEND_ORIGINS", "http://localhost:3000").split(",")
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Authorization", "Content-Type", "X-Problem-Token"],
    )
    app.include_router(productions_router, prefix="/api/v1")
    app.include_router(problems_router, prefix="/api/v1")
    app.include_router(internal_contributions_router, prefix="/api/v1")
    app.include_router(public_contributions_router, prefix="/api/v1")

    @app.get("/health", tags=["operations"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
