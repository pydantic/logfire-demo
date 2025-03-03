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
        if not pool:
            raise ValueError('Failed to create pool')
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

CREATE TABLE IF NOT EXISTS llm_results (
    questions_hash TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    chunks JSON  -- isn't filtered, so use JSON instead of JSONB
);

CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS embeddings (
    id SERIAL PRIMARY KEY,                -- Unique ID for each entry
    source TEXT NOT NULL,                 -- "github_issue", "slack_message", "pydantic_docs", ...
    external_reference TEXT,              -- GitHub link, Slack message ID
    parent TEXT,                          -- GitHub issue, Thread TS (for Slack threads)
    text TEXT NOT NULL,                   -- The actual text content
    hash TEXT UNIQUE NOT NULL,            -- Hash of the text content
    author TEXT,                          -- Author of the message
    event_ts TIMESTAMPTZ DEFAULT NOW(),   -- Timestamp of when the event occurred
    created_at TIMESTAMPTZ DEFAULT NOW(), -- Timestamp of when the entry was created
    embedding VECTOR(1536)                -- For storing embeddings
);

CREATE TABLE IF NOT EXISTS github_contents (
    id SERIAL PRIMARY KEY,                     -- Unique ID for each entry
    project TEXT NOT NULL,                     -- "pydantic", "logfire"
    source TEXT NOT NULL,                      -- "issue"
    content_id BIGINT NOT NULL,                -- GitHub content ID
    external_reference TEXT NOT NULL,          -- GitHub link
    text TEXT NOT NULL,                        -- The actual text content
    event_ts TIMESTAMPTZ DEFAULT NOW(),        -- Timestamp of when the event occurred
    created_at TIMESTAMPTZ DEFAULT NOW(),      -- Timestamp of when the entry was created
    updated_at TIMESTAMPTZ DEFAULT NOW(),      -- Timestamp of when the entry was last updated
    embedding VECTOR(1536),                    -- For storing embeddings
    similar_issues JSONB,                      -- Similar issues
    unique (project, source, content_id)       -- Unique constraint
);

CREATE TABLE IF NOT EXISTS slack_messages (
    id SERIAL PRIMARY KEY,                     -- Unique ID for each entry
    channel TEXT NOT NULL,                     -- Slack channel
    author TEXT NOT NULL,                      -- Message author
    message_id TEXT NOT NULL,                  -- Slack message ID
    event_ts TEXT NOT NULL,                    -- Timestamp of when the event occurred (text)
    parent_event_ts TEXT,                      -- Slack message thread timestamp
    text TEXT NOT NULL,                        -- The actual text content
    ts TIMESTAMPTZ,                            -- Message timestamp
    created_at TIMESTAMPTZ DEFAULT NOW(),      -- Timestamp of when the entry was created
    embedding VECTOR(1536)                     -- For storing embeddings
);
""")
