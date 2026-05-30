from __future__ import annotations

from dormammu.config import AppConfig
from dormammu.web.app import create_app
from dormammu.web.auth import validate_server_auth_config


def run_web_server(
    config: AppConfig,
    *,
    host: str,
    port: int,
    token: str | None,
) -> None:
    validate_server_auth_config(
        host=host,
        token=token,
        password_hash=config.web_config.password_hash,
        allow_initial_setup=True,
    )
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - exercised by CLI guard
        raise ImportError("uvicorn is required for dormammu web") from exc

    app = create_app(config, token=token)
    uvicorn.run(app, host=host, port=port)
