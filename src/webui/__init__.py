from __future__ import annotations as _annotations

import os
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

print(os.environ, flush=True)
print(os.environ.get('LOGFIRE_TOKEN'), flush=True)
os.environ.update(
    OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SERVER_REQUEST='.*',
    OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SERVER_RESPONSE='.*',
)
logfire.configure(send_to_logfire=bool(os.getenv('LOGFIRE_TOKEN')), service_name='webui')
AsyncPGInstrumentor().instrument()


class Settings(BaseSettings):
    pg_dsn: str = 'postgres://postgres:postgres@localhost/logfire_demo'
    create_database: bool = True


@asynccontextmanager
async def lifespan(app_: FastAPI):
    settings: Settings = app_.state.settings  # type: ignore
    async with AsyncExitStack() as stack:
        app_.state.httpx_client = httpx_client = await stack.enter_async_context(AsyncClient())
        HTTPXClientInstrumentor.instrument_client(httpx_client)
        app_.state.db = await stack.enter_async_context(
            Database.create(settings.pg_dsn, True, settings.create_database)
        )
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


@app.get('/health', response_class=PlainTextResponse)
async def health(db: Database) -> str:
    async with db.acquire() as con:
        version = await con.fetchval('SELECT version()')
    return f'pg version: {version}'


@app.get('/favicon.ico', status_code=404, response_class=PlainTextResponse)
async def favicon_ico() -> str:
    return 'page not found'


@app.get('/{path:path}')
async def html_landing() -> HTMLResponse:
    return HTMLResponse(prebuilt_html(title='Logfire Demo'))


def run():
    import uvicorn

    uvicorn.run(app, host='0.0.0.0', port=8000, log_level='info')
