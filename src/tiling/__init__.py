from __future__ import annotations as _annotations

import os
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Annotated

import logfire
from annotated_types import Ge, Gt, Le, Lt
from fastapi import FastAPI, Header, Response
from fastapi.responses import PlainTextResponse
from httpx import AsyncClient
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from ..common import AsyncClientDep
from .build_map import BuildMap

os.environ.update(
    OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SERVER_REQUEST='.*',
    OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SERVER_RESPONSE='.*',
)
logfire.configure(service_name='tiling')


@asynccontextmanager
async def lifespan(app_: FastAPI):
    async with AsyncExitStack() as stack:
        app_.state.httpx_client = httpx_client = await stack.enter_async_context(AsyncClient())
        HTTPXClientInstrumentor.instrument_client(httpx_client)
        yield


app = FastAPI(lifespan=lifespan)
logfire.instrument_fastapi(app)


@app.get('/', response_class=PlainTextResponse)
@app.head('/', include_in_schema=False)
async def index() -> str:
    return 'Tiling service\n'


@app.get('/robots.txt', response_class=PlainTextResponse)
@app.head('/robots.txt', include_in_schema=False)
async def robots_txt() -> str:
    return 'User-agent: *\nDisallow: /\n'


@app.get('/health', response_class=PlainTextResponse)
@app.head('/health', include_in_schema=False)
async def health() -> str:
    return 'OK\n'


@app.get('/favicon.ico', status_code=404, response_class=PlainTextResponse)
@app.head('/favicon.ico', include_in_schema=False)
async def favicon_ico() -> str:
    return 'page not found'


@app.get('/map.jpg')
async def get_map(
    http_client: AsyncClientDep,
    lat: Annotated[float, Ge(-85), Le(85)],
    lng: Annotated[float, Ge(-180), Le(180)],
    zoom: Annotated[int, Gt(0), Lt(20)] = 10,
    width: Annotated[int, Ge(95), Le(1000)] = 600,
    height: Annotated[int, Ge(60), Le(1000)] = 400,
    scale: Annotated[int, Ge(1), Le(2)] = 1,
    referer: Annotated[str | None, Header()] = None,
) -> Response:
    builder = BuildMap(
        http_client=http_client, referrer=referer, lat=lat, lng=lng, zoom=zoom, width=width, height=height, scale=scale
    )
    image = await builder.run()
    return Response(
        content=image,
        media_type='image/jpeg',
        headers={'Cache-Control': 'max-age=1209600', 'X-Robots-Tag': 'noindex'},  # 1209600 is 14 days
    )


def run():
    import uvicorn

    uvicorn.run(app, host='0.0.0.0', port=8000, log_level='info')
