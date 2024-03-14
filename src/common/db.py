import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Self, Annotated
from fastapi import Request, Depends

import logfire
from asyncpg.pool import Pool, create_pool
from asyncpg.connection import Connection

__all__ = ('Database',)


@dataclass
class _Database:
    """
    Wrapper for asyncpg with some utilities and usable as a fastapi dependency.
    """

    _pool: Pool

    @classmethod
    @asynccontextmanager
    async def create(cls, dsn: str, prepare_db: bool = False) -> AsyncIterator[Self]:
        pool = await create_pool(dsn)
        try:
            slf = cls(_pool=pool)
            if prepare_db:
                with logfire.span('preparing DB'):
                    async with slf.acquire_trans() as conn:
                        await _prepare_db(conn)
            yield slf
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


async def _prepare_db(conn: Connection) -> None:
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
""")
    from .cities import create_cities

    await create_cities(conn)
