from fastapi import FastAPI

from pci.productions.router import router as productions_router


def create_app() -> FastAPI:
    app = FastAPI(title="Pernambuco Ciência para Inovação", version="0.1.0")
    app.include_router(productions_router, prefix="/api/v1")

    @app.get("/health", tags=["operations"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
