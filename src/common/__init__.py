from typing import Annotated

from httpx import AsyncClient
from fastapi import Request, Depends


def get_http_client(request: Request) -> AsyncClient:
    return request.app.state.httpx_client


AsyncClientDep = Annotated[AsyncClient, Depends(get_http_client)]
