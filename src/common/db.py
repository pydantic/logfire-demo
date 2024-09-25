import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Self
from urllib.parse import urlparse

import asyncpg
import logfire
from asyncpg.connection import Connection
from fastapi import Depends, Request

__all__ = ('Database',)


@dataclass
class _Database:
    """
    Wrapper for asyncpg with some utilities and usable as a fastapi dependency.
    """

    _pool: asyncpg.Pool

    @classmethod
    @asynccontextmanager
    async def create(cls, dsn: str, prepare_db: bool = False, create_database: bool = False) -> AsyncIterator[Self]:
        if prepare_db:
            with logfire.span('prepare DB'):
                await _prepare_db(dsn, create_database)
        pool = await asyncpg.create_pool(dsn)
        try:
            yield cls(_pool=pool)
        finally:
            await asyncio.wait_for(pool.close(), timeout=2.0)

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[Connection]:
        con = await self._pool.acquire()
        try:
            yield con
        finally:
            await self._pool.release(con)

    @asynccontextmanager
    async def acquire_trans(self) -> AsyncIterator[Connection]:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                yield conn


def _get_db(request: Request) -> _Database:
    return request.app.state.db


Database = Annotated[_Database, Depends(_get_db)]


async def _prepare_db(dsn: str, create_database: bool) -> None:
    if create_database:
        with logfire.span('check and create DB'):
            parse_result = urlparse(dsn)
            database = parse_result.path.lstrip('/')
            server_dsn = dsn[: dsn.rindex('/')]
            conn = await asyncpg.connect(server_dsn)
            try:
                db_exists = await conn.fetchval('SELECT 1 FROM pg_database WHERE datname = $1', database)
                if not db_exists:
                    await conn.execute(f'CREATE DATABASE {database}')
            finally:
                await conn.close()

    with logfire.span('create schema'):
        conn = await asyncpg.connect(dsn)
        try:
            async with conn.transaction():
                await _create_schema(conn)
        finally:
            await conn.close()


async def _create_schema(conn: Connection) -> None:
    await conn.execute("""
CREATE TABLE IF NOT EXISTS cities (
    id INT PRIMARY KEY,
    city TEXT NOT NULL,
    city_ascii TEXT NOT NULL,
    lat NUMERIC NOT NULL,
    lng NUMERIC NOT NULL,
    country TEXT NOT NULL,
    iso2 TEXT NOT NULL,
    iso3 TEXT NOT NULL,
    admin_name TEXT,
    capital TEXT,
    population INT NOT NULL
);
CREATE INDEX IF NOT EXISTS cities_country_idx ON cities (country);
CREATE INDEX IF NOT EXISTS cities_iso3_idx ON cities (iso3);
CREATE INDEX IF NOT EXISTS cities_population_idx ON cities (population desc);

CREATE TABLE IF NOT EXISTS chats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS chats_created_at_idx ON chats (created_at desc);

CREATE TABLE IF NOT EXISTS messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id UUID NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    role TEXT NOT NULL,
    message TEXT NOT NULL,
    cost INT
);
CREATE INDEX IF NOT EXISTS messages_chat_id_idx ON messages (chat_id);
CREATE INDEX IF NOT EXISTS messages_created_at_idx ON messages (created_at);

CREATE TABLE IF NOT EXISTS repo_clocs (
    repo TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    counts JSONB
);

CREATE TABLE IF NOT EXISTS llm_results (
    questions_hash TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    chunks JSON  -- isn't filtered, so use JSON instead of JSONB
);
""")
    from .cities import create_cities

    await create_cities(conn)
