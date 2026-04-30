# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""
FastAPI application for the Incident Response Env Environment.

This module creates an HTTP server that exposes the IncidentResponseEnvironment
over HTTP and WebSocket endpoints, and mounts a custom Gradio playground at
``/web`` that:

  * shows the legal Role values directly in the field label,
  * binds each command to an integer ID with a visible mapping table,
  * embeds the GRPO training notebook below the playground.

Endpoints:
    - POST /reset: Reset the environment
    - POST /step: Execute an action
    - GET /state: Get current environment state
    - GET /schema: Get action/observation schemas
    - WS /ws: WebSocket endpoint for persistent sessions
    - GET /web: Custom Gradio playground (this file's UI)
    - GET /web/notebook.html: Server-rendered HTML view of the GRPO notebook

Usage:
    # Development (with auto-reload):
    uvicorn server.app:app --reload --host 0.0.0.0 --port 8000

    # Production:
    uvicorn server.app:app --host 0.0.0.0 --port 8000 --workers 4
"""

from pathlib import Path
from typing import Any, Dict, Optional

try:
    import gradio as gr
    from fastapi import Body, HTTPException, WebSocket, WebSocketDisconnect, status
    from fastapi.responses import FileResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles
    from openenv.core.env_server.gradio_theme import (
        OPENENV_GRADIO_CSS,
        OPENENV_GRADIO_THEME,
    )
    from openenv.core.env_server.http_server import create_fastapi_app
    from openenv.core.env_server.web_interface import (
        WebInterfaceManager,
        get_quick_start_markdown,
        load_environment_metadata,
    )
except Exception as e:  # pragma: no cover
    raise ImportError(
        "openenv (with gradio) is required for the web interface. "
        "Install dependencies with '\n    uv sync\n'"
    ) from e

try:
    from ..models import IncidentResponseAction, IncidentResponseObservation
    from .custom_ui import build_custom_ui, prepare_notebook_html
    from .incident_response_env_environment import IncidentResponseEnvironment
except (ModuleNotFoundError, ImportError):
    from models import IncidentResponseAction, IncidentResponseObservation
    from server.custom_ui import build_custom_ui, prepare_notebook_html
    from server.incident_response_env_environment import IncidentResponseEnvironment


# ---------------------------------------------------------------------------
# Render the GRPO notebook to HTML once at import time so the embed loads fast.
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_NOTEBOOK_SRC = _PROJECT_ROOT / "qwen0-5b.ipynb"
_NOTEBOOK_HTML = Path(__file__).resolve().parent / "_notebook.html"

if _NOTEBOOK_SRC.exists():
    try:
        prepare_notebook_html(_NOTEBOOK_SRC, _NOTEBOOK_HTML)
    except Exception as exc:  # pragma: no cover - keep the server starting
        _NOTEBOOK_HTML.write_text(
            f"<html><body><pre>Failed to prepare notebook HTML: {exc}</pre></body></html>",
            encoding="utf-8",
        )
else:
    _NOTEBOOK_HTML.write_text(
        "<html><body><p><em>Notebook not found in project root.</em></p></body></html>",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Build the FastAPI app + custom Gradio UI.
# ---------------------------------------------------------------------------
app = create_fastapi_app(
    IncidentResponseEnvironment,
    IncidentResponseAction,
    IncidentResponseObservation,
    max_concurrent_envs=1,
)

_metadata = load_environment_metadata(IncidentResponseEnvironment, "incident_response_env")
_web_manager = WebInterfaceManager(
    IncidentResponseEnvironment,
    IncidentResponseAction,
    IncidentResponseObservation,
    _metadata,
)
_quick_start_md = get_quick_start_markdown(
    _metadata, IncidentResponseAction, IncidentResponseObservation
)


# These web-facing routes mirror what `create_web_interface_app` registers so
# our custom UI keeps the same client contract (reset / step / state / ws/ui /
# /web/metadata). They MUST be declared before mounting Gradio at /web so that
# FastAPI matches them in preference to the Gradio sub-app.
@app.get("/", include_in_schema=False)
async def _web_root_redirect():
    return RedirectResponse(url="/web/")


@app.get("/web", include_in_schema=False)
async def _web_no_slash():
    return RedirectResponse(url="/web/")


@app.get("/web/metadata")
async def _web_metadata():
    return _web_manager.metadata.model_dump()


@app.get("/web/notebook.html", include_in_schema=False)
async def _web_notebook():
    return FileResponse(str(_NOTEBOOK_HTML), media_type="text/html")


_ASSETS_DIR = _PROJECT_ROOT / "assets"
if _ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(_ASSETS_DIR)), name="assets")


@app.websocket("/ws/ui")
async def _websocket_ui_endpoint(websocket: WebSocket):
    await _web_manager.connect_websocket(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await _web_manager.disconnect_websocket(websocket)


@app.post("/web/reset")
async def _web_reset(request: Optional[Dict[str, Any]] = Body(default=None)):
    return await _web_manager.reset_environment(request)


@app.post("/web/step")
async def _web_step(request: Dict[str, Any]):
    action_data = request.get("action", request)
    return await _web_manager.step_environment(action_data)


@app.get("/web/state")
async def _web_state():
    try:
        return _web_manager.get_state()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


_custom_blocks = build_custom_ui(
    _web_manager,
    _metadata,
    _quick_start_md,
    notebook_iframe_url="/web/notebook.html",
)
app = gr.mount_gradio_app(
    app,
    _custom_blocks,
    path="/web",
    theme=OPENENV_GRADIO_THEME,
    css=OPENENV_GRADIO_CSS,
)


def main(host: str = "0.0.0.0", port: int = 8000):
    """
    Entry point for direct execution via uv run or python -m.

    This function enables running the server without Docker:
        uv run --project . server
        uv run --project . server --port 8001
        python -m incident_response_env.server.app

    Args:
        host: Host address to bind to (default: "0.0.0.0")
        port: Port number to listen on (default: 8000)

    For production deployments, consider using uvicorn directly with
    multiple workers:
        uvicorn incident_response_env.server.app:app --workers 4
    """
    import os

    # The Gradio UI relies on the OpenEnv web interface scaffolding, which
    # only initializes when ENABLE_WEB_INTERFACE is truthy. Setting it here
    # makes `python -m server.app` show the playground without extra setup.
    os.environ.setdefault("ENABLE_WEB_INTERFACE", "1")

    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
