"""Side-effect-free ASGI factory and explicit Uvicorn launcher."""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from dataguard.config import RuntimeSettings
from dataguard.production import create_production_app, create_runtime


def application_factory():
    """Read only the closed environment and construct an unstarted application."""

    try:
        configured_root = Path(os.environ.get("DATAGUARD_PROJECT_ROOT", "."))
        project_root = configured_root if configured_root.is_absolute() else Path.cwd() / configured_root
        settings_env = {key: value for key, value in os.environ.items()
                        if key.startswith("DATAGUARD_") and key != "DATAGUARD_PROJECT_ROOT"}
        settings = RuntimeSettings.from_env(settings_env)
        return create_production_app(create_runtime(project_root, settings))
    except Exception:
        raise RuntimeError("DataGuard server configuration is invalid.") from None


def main() -> None:
    """Launch the fixed local API without importing an already-started singleton."""

    try:
        settings_env = {key: value for key, value in os.environ.items()
                        if key.startswith("DATAGUARD_") and key != "DATAGUARD_PROJECT_ROOT"}
        settings = RuntimeSettings.from_env(settings_env)
    except Exception:
        raise RuntimeError("DataGuard server configuration is invalid.") from None
    host = "0.0.0.0" if settings.allow_container_host_gateway else "127.0.0.1"
    uvicorn.run("dataguard.server:application_factory", factory=True,
                host=host, port=8000, log_config=None, access_log=False)


if __name__ == "__main__":
    main()
