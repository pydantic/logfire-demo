from httpx import AsyncClient
from fastapi import Request


def get_http_client(request: Request) -> AsyncClient:
    return request.app.state.httpx_client
