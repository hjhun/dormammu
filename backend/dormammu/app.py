from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from dormammu.config import AppConfig
from dormammu.state import StateRepository


def create_app(config: AppConfig | None = None) -> Any:
    """Create the optional local HTTP app for visibility and control."""

    try:
        from fastapi import FastAPI
        from fastapi.staticfiles import StaticFiles
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "FastAPI is not installed. Install the project dependencies before "
            "starting the local web app."
        ) from exc

    from dormammu.api.routes_runs import RunController, router as runs_router
    from dormammu.api.routes_state import router as state_router
    from dormammu.api.routes_ui import router as ui_router

    app_config = config or AppConfig.load()
    state_repository = StateRepository(app_config)

    @asynccontextmanager
    async def lifespan(_: Any):
        state_repository.ensure_bootstrap_state()
        yield

    app = FastAPI(
        title=app_config.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.config = app_config
    app.state.state_repository = state_repository
    app.state.run_controller = RunController(app_config, state_repository)
    app.mount("/assets", StaticFiles(directory=str(app_config.frontend_dir)), name="assets")
    app.include_router(runs_router)
    app.include_router(state_router)
    app.include_router(ui_router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "app": app_config.app_name}

    @app.get("/config")
    def show_config() -> dict[str, object]:
        return app_config.to_dict()

    @app.get("/state/bootstrap")
    def show_bootstrap_state() -> dict[str, str]:
        artifacts = state_repository.ensure_bootstrap_state()
        return artifacts.to_dict()

    return app
