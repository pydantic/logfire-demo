import asyncio
import logging.config

import asyncpg
import logfire
from arq import cron
from arq.connections import RedisSettings
from arq.worker import run_worker
from httpx import AsyncClient
from openai import AsyncOpenAI

from ..common import GeneralSettings
from .docs_embeddings import update_docs_embeddings

logfire.configure(service_name='worker')
logfire.instrument_system_metrics()
logfire.instrument_asyncpg()
logfire.instrument_httpx(capture_all=True)


settings = GeneralSettings()  # type: ignore


async def startup(ctx):
    openai_http_client = AsyncClient()
    openai_client = openai_client = AsyncOpenAI(http_client=openai_http_client)

    client = AsyncClient()
    ctx.update(
        client=client,
        pg_pool=await asyncpg.create_pool(settings.pg_dsn),
        openai_client=openai_client,
    )


async def shutdown(ctx):
    await ctx['client'].aclose()
    await ctx['openai_client'].close()
    await asyncio.wait_for(ctx['pg_pool'].close(), timeout=2.0)


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
    functions = [pydantic_doc_embeddings, pydantic_ai_doc_embeddings, logfire_doc_embeddings]
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
