import hashlib
from datetime import datetime
from typing import Any, Literal

import logfire
import tiktoken
from asyncpg import Connection
from openai import AsyncOpenAI

TOKEN_LIMIT = 8192  # OpenAI embedding model token limit


def count_tokens(text: str, model: str = 'text-embedding-ada-002') -> int:
    """Counts the number of tokens in a given text using OpenAI's tiktoken."""
    encoding = tiktoken.encoding_for_model(model)
    return len(encoding.encode(text))


def truncate_text_to_token_limit(text: str, model: str = 'text-embedding-ada-002', max_tokens: int = 8192) -> str:
    """Truncate text to fit within the token limit for embeddings."""
    encoding = tiktoken.encoding_for_model(model)
    tokens = encoding.encode(text)  # Convert text to tokens

    if len(tokens) > max_tokens:
        tokens = tokens[:max_tokens]  # Truncate to max tokens

    return encoding.decode(tokens)  # Convert tokens back to text


async def generate_embedding(openai_client: AsyncOpenAI, text: str) -> list[float]:
    with logfire.span('call openai'):
        response = await openai_client.embeddings.create(input=text, model='text-embedding-ada-002')
        return response.data[0].embedding


def hash_text(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


EmbeddingsSource = Literal['slack_message', 'github_issue', 'pydantic_docs', 'pydantic_ai_docs', 'logfire_docs']


async def get_stored_embeddings_hash_by_source(conn: Connection[Any], source: EmbeddingsSource) -> list[str]:
    hashes = await conn.fetch('SELECT hash FROM embeddings WHERE source=$1', source)
    return [hash[0] for hash in hashes]


async def create_embeddings(
    conn: Connection[Any],
    source: EmbeddingsSource,
    text: str,
    text_hash: str,
    embedding: list[list[float]],
    event_ts: datetime | None = None,
    external_reference: str | None = None,
    author: str | None = None,
    parent: str | None = None,
) -> None:
    """Create a new embeddings in the database"""
    embedding_str = '[' + ','.join(map(str, embedding)) + ']'
    await conn.execute(
        """
        INSERT INTO embeddings (source, external_reference, text, hash, author, event_ts, embedding, parent)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        source,
        external_reference,
        text,
        text_hash,
        author,
        event_ts,
        embedding_str,
        parent,
    )


async def delete_embeddings_by_hash(conn: Connection[Any], hashes: set[str], source: EmbeddingsSource) -> None:
    await conn.execute('DELETE FROM embeddings WHERE hash = ANY($1) AND source=$2', hashes, source)
