from __future__ import annotations as _annotations

import sys
from contextlib import asynccontextmanager, AsyncExitStack

import logfire

from pydantic_settings import BaseSettings
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastui import prebuilt_html
from fastui.auth import fastapi_auth_exception_handling
from fastui.dev import dev_fastapi_app
from httpx import AsyncClient
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from ..common.db import Database
from .main import router as main_router
from .table import router as table_router
from .llm import router as llm_router

logfire.configure()
AsyncPGInstrumentor().instrument()


class Settings(BaseSettings):
    pg_dsn: str = 'postgres://postgres:postgres@localhost/logfire_demo'


@asynccontextmanager
async def lifespan(app_: FastAPI):
    settings: Settings = app_.state.settings  # type: ignore
    async with AsyncExitStack() as stack:
        app_.state.httpx_client = httpx_client = await stack.enter_async_context(AsyncClient())
        HTTPXClientInstrumentor.instrument_client(httpx_client)
        app_.state.db = await stack.enter_async_context(Database.create(settings.pg_dsn, True))
        yield


# This doesn't have any effect yet, needs https://github.com/pydantic/FastUI/issues/198
frontend_reload = '--reload' in sys.argv
if frontend_reload:
    # dev_fastapi_app reloads in the browser when the Python source changes
    app = dev_fastapi_app(lifespan=lifespan)
else:
    app = FastAPI(lifespan=lifespan)

app.state.settings = Settings()  # type: ignore
logfire.instrument_fastapi(app)

fastapi_auth_exception_handling(app)
app.include_router(table_router, prefix='/api/table')
app.include_router(llm_router, prefix='/api/llm')
app.include_router(main_router, prefix='/api')


@app.get('/robots.txt', response_class=PlainTextResponse)
async def robots_txt() -> str:
    return 'User-agent: *\nDisallow: /'


@app.get('/favicon.ico', status_code=404, response_class=PlainTextResponse)
async def favicon_ico() -> str:
    return 'page not found'


@app.get('/{path:path}')
async def html_landing() -> HTMLResponse:
    return HTMLResponse(prebuilt_html(title='Logfire Demo'))
