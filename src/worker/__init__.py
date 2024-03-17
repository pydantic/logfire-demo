import asyncio
import json

import asyncpg
import logfire

from httpx import AsyncClient

from ..common import GeneralSettings
from .cloc import cloc_logic

from arq.connections import RedisSettings
from arq.worker import run_worker


logfire.configure(service_name='worker')


async def cloc(ctx, repo: str):
    """
    Count the lines of code, by language, in a GitHub repository.
    """
    pg_pool: asyncpg.Pool = ctx['pg_pool']
    status = await pg_pool.fetchval('SELECT status FROM repo_clocs WHERE repo = $1', repo)
    if status == 'done':
        logfire.info('cloc already done {repo=}', repo=repo)
        return

    client = ctx['client']
    try:
        with logfire.span('cloc {repo=}', repo=repo) as span:
            file_types = await asyncio.wait_for(cloc_logic(client, repo), 60)
            span.set_attribute('file_types', file_types)
        data = json.dumps(file_types)
        await pg_pool.execute("UPDATE repo_clocs SET status = 'done', counts = $1 WHERE repo = $2", data, repo)
    except Exception:
        await pg_pool.execute("UPDATE repo_clocs SET status = 'error' WHERE repo = $1", repo)
        raise


class Settings(GeneralSettings):
    github_token: str


settings = Settings()  # type: ignore


async def startup(ctx):
    headers = {'Accept': 'application/vnd.github.v3+json', 'Authorization': f'token {settings.github_token}'}
    ctx.update(
        client=AsyncClient(headers=headers),
        pg_pool=await asyncpg.create_pool(settings.pg_dsn),
    )


async def shutdown(ctx):
    await ctx['client'].aclose()
    await asyncio.wait_for(ctx['pg_pool'].close(), timeout=2.0)


class WorkerSettings:
    functions = [cloc]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_dsn)


async def run():
    run_worker(WorkerSettings)  # type: ignore
