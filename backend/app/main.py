from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app.api.routes import GameLocks, router
from app.config import Settings
from app.db.session import init_db, make_engine, make_sessionmaker
from app.domain.service import DomainError
from app.realtime.hub import Hub


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = make_engine(settings.database_url)
    init_db(engine)

    app = FastAPI(title="MoneyShift", version="0.1.0")
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.hub = Hub()
    app.state.locks = GameLocks()

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse({"detail": exc.message, "code": exc.code}, status_code=exc.status)

    app.include_router(router)

    static_dir = settings.resolve_static_dir()
    if static_dir:
        root = static_dir.resolve()

        updating = HTMLResponse(
            "<!doctype html><meta charset=utf-8><meta http-equiv=refresh content=3>"
            "<meta name=viewport content='width=device-width, initial-scale=1'>"
            "<body style='font-family:system-ui;padding:24px'><h2>MoneyShift is updating</h2>"
            "<p>This page will reload in a moment.</p>",
            status_code=503,
            headers={"Retry-After": "3"},
        )

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"detail": "Not found"}, status_code=404)
            # The app can be rebuilt while the server runs; answer politely instead of erroring.
            index = root / "index.html"
            if not index.is_file():
                return updating
            candidate = (root / path).resolve()
            if path and candidate.is_file() and root in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(index)

    return app
