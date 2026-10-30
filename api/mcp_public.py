"""Minimal ASGI surface for exposing only JurisAI MCP and its OAuth flow.

Run on a loopback-only port behind a trusted HTTPS tunnel. The normal JurisAI
API, including account and document routes, is deliberately not mounted here.
"""

import logging
import time

from fastapi import FastAPI, Request

from api.mcp_oauth import router as oauth_router
from api.mcp_server import router as mcp_router

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def log_mcp_transport(request: Request, call_next):
    """Transport diagnostics only: never log tokens, query strings or bodies."""
    started = time.monotonic()
    logger = logging.getLogger("uvicorn.error")
    path = request.url.path if request.url.path in {"/mcp", "/oauth/token"} else "[other]"
    try:
        response = await call_next(request)
    except Exception as exc:
        logger.error("MCP transport method=%s path=%s exception=%s", request.method,
                     path, type(exc).__name__)
        raise
    logger.info("MCP transport method=%s path=%s status=%s elapsed_ms=%s", request.method,
                path, response.status_code, round((time.monotonic() - started) * 1000))
    return response


app.include_router(oauth_router)
app.include_router(mcp_router)
