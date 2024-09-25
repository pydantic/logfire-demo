import asyncio
import json
import logging.config
from typing import Annotated

import asyncpg
import logfire
from annotated_types import MinLen
from arq.connections import RedisSettings
from arq.worker import run_worker
from httpx import AsyncClient
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from ..common import GeneralSettings
from .cloc import cloc_recursive

logfire.configure(service_name='worker')
logfire.instrument_asyncpg()


class Settings(GeneralSettings):
    github_token: Annotated[str, MinLen(1)]


settings = Settings()  # type: ignore


async def startup(ctx):
    headers = {'Accept': 'application/vnd.github.v3+json', 'Authorization': f'token {settings.github_token}'}
    client = AsyncClient(headers=headers, follow_redirects=True)
    HTTPXClientInstrumentor.instrument_client(client)
    ctx.update(
        client=client,
        pg_pool=await asyncpg.create_pool(settings.pg_dsn),
    )


async def shutdown(ctx):
    await ctx['client'].aclose()
    await asyncio.wait_for(ctx['pg_pool'].close(), timeout=2.0)


async def cloc(ctx, repo: str):
    """Count lines of code by language, in a GitHub repository."""
    with logfire.span('cloc {repo=}', repo=repo) as span:
        pg_pool: asyncpg.Pool = ctx['pg_pool']
        status = await pg_pool.fetchval('SELECT status FROM repo_clocs WHERE repo = $1', repo)
        if status == 'done':
            logfire.info('cloc already done {repo=}', repo=repo)
            return

        client = ctx['client']
        try:
            file_types = await asyncio.wait_for(cloc_recursive(client, repo), 60)
            span.set_attribute('file_types', file_types)
            data = json.dumps(file_types)
            await pg_pool.execute("UPDATE repo_clocs SET status = 'done', counts = $1 WHERE repo = $2", data, repo)
        except Exception:
            await pg_pool.execute("UPDATE repo_clocs SET status = 'error' WHERE repo = $1", repo)
            raise


class WorkerSettings:
    functions = [cloc]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_dsn)


def run():
    logging.config.dictConfig(
        {
            'version': 1,
            'disable_existing_loggers': False,
            'handlers': {
                'logfire': {'level': 'INFO', 'class': 'logfire.integrations.logging.LogfireLoggingHandler'},
            },
            'loggers': {'arq': {'handlers': ['logfire'], 'level': 'INFO'}},
        }
    )

    run_worker(WorkerSettings)  # type: ignore
