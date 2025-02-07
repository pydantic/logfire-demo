import asyncio
import json
import logging.config
from typing import Annotated

import asyncpg
import logfire
from annotated_types import MinLen
from arq import cron
from arq.connections import RedisSettings
from arq.worker import run_worker
from httpx import AsyncClient
from openai import AsyncOpenAI
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from ..common import GeneralSettings
from .cloc import cloc_recursive
from .docs_embeddings import update_docs_embeddings

logfire.configure(service_name='worker')
logfire.instrument_system_metrics()
logfire.instrument_asyncpg()


class Settings(GeneralSettings):
    github_token: Annotated[str, MinLen(1)]


settings = Settings()  # type: ignore


async def startup(ctx):
    headers = {'Accept': 'application/vnd.github.v3+json', 'Authorization': f'token {settings.github_token}'}
    client = AsyncClient(headers=headers, follow_redirects=True)
    HTTPXClientInstrumentor.instrument_client(client)
    openai_http_client = AsyncClient()
    HTTPXClientInstrumentor.instrument_client(openai_http_client)
    openai_client = openai_client = AsyncOpenAI(http_client=openai_http_client)
    ctx.update(
        client=client,
        pg_pool=await asyncpg.create_pool(settings.pg_dsn),
        openai_client=openai_client,
    )


async def shutdown(ctx):
    await ctx['client'].aclose()
    await ctx['openai_client'].close()
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


async def pydantic_doc_embeddings(ctx) -> None:
    """Update the embeddings for the pydantic documentation."""
    with logfire.span('update pydantic ai docs embeddings'):
        await update_docs_embeddings(
            ctx['client'],
            ctx['pg_pool'],
            ctx['openai_client'],
            'https://docs.pydantic.dev/dev/llms.txt',
            'pydantic_docs',
        )


async def pydantic_ai_doc_embeddings(ctx) -> None:
    """Update the embeddings for the pydantic ai documentation."""
    with logfire.span('update pydantic ai docs embeddings'):
        await update_docs_embeddings(
            ctx['client'], ctx['pg_pool'], ctx['openai_client'], 'https://ai.pydantic.dev/llms.txt', 'pydantic_ai_docs'
        )


async def logfire_doc_embeddings(ctx) -> None:
    """Update the embeddings for the logfire documentation."""
    with logfire.span('update logfire docs embeddings'):
        await update_docs_embeddings(
            ctx['client'],
            ctx['pg_pool'],
            ctx['openai_client'],
            'https://logfire.pydantic.dev/docs/llms.txt',
            'logfire_docs',
        )


class WorkerSettings:
    functions = [cloc, pydantic_doc_embeddings, pydantic_ai_doc_embeddings, logfire_doc_embeddings]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_dsn)
    cron_jobs = [
        cron(pydantic_ai_doc_embeddings, hour={10, 22}, minute=0),
        cron(logfire_doc_embeddings, hour={1, 13}, minute=0),
        cron(pydantic_doc_embeddings, hour={2, 14}, minute=0),
    ]


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
