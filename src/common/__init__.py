import urllib.parse
from typing import Annotated, Any

from httpx import AsyncClient
from fastapi import Request, Depends


def get_http_client(request: Request) -> AsyncClient:
    return request.app.state.httpx_client


AsyncClientDep = Annotated[AsyncClient, Depends(get_http_client)]


def build_params(**params: Any) -> str:
    return urllib.parse.urlencode({k: str(v) for k, v in params.items()})
