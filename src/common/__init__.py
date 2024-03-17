import urllib.parse
from typing import Annotated, Any

from httpx import AsyncClient
from fastapi import Request, Depends
from arq import ArqRedis
from pydantic_settings import BaseSettings


def _get_http_client(request: Request) -> AsyncClient:
    return request.app.state.httpx_client


AsyncClientDep = Annotated[AsyncClient, Depends(_get_http_client)]


def build_params(**params: Any) -> str:
    return urllib.parse.urlencode({k: str(v) for k, v in params.items()})


def _arq_redis(request: Request) -> ArqRedis:
    return request.app.state.arq_redis


ArqRedisDep = Annotated[ArqRedis, Depends(_arq_redis)]


class GeneralSettings(BaseSettings):
    pg_dsn: str = 'postgres://postgres:postgres@localhost/logfire_demo'
    redis_dsn: str = 'redis://localhost:63790'
