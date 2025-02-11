from datetime import datetime
from typing import Any, Literal

from asyncpg import Connection

from ..embeddings import hash_text

GithubContentProject = Literal['pydantic', 'logfire', 'pydantic-ai']
GithubContentSource = Literal['issue']


async def create_github_content(
    conn: Connection,
    project: GithubContentProject,
    source: GithubContentSource,
    content_id: str,
    external_reference: str,
    text: str,
    event_ts: datetime,
    embedding: list[list[float]],
) -> None:
    """Save GitHub content to the database."""
    embedding_str = '[' + ','.join(map(str, embedding)) + ']'
    await conn.execute(
        """
        INSERT INTO github_contents (project, source, content_id, external_reference, text, hash, event_ts, embedding)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        project,
        source,
        content_id,
        external_reference,
        text,
        hash_text(text),
        event_ts,
        embedding_str,
    )


async def fetch_github_content(
    conn: Connection,
    project: GithubContentProject,
    source: GithubContentSource,
    content_id: int,
) -> dict[str, Any]:
    """Fetch GitHub content from the database by ID."""
    return await conn.fetchrow(
        """
        SELECT id, text, embedding FROM github_contents WHERE project=$1 AND source=$2 AND content_id=$3
        """,
        project,
        source,
        content_id,
    )


async def update_github_content(
    conn: Connection,
    project: GithubContentProject,
    source: GithubContentSource,
    content_id: int,
    text: str,
    embedding: list[list[float]],
) -> None:
    """Update GitHub content in the database."""
    embedding_str = '[' + ','.join(map(str, embedding)) + ']'
    await conn.execute(
        """
        UPDATE github_contents SET text=$1, hash=$2, embedding=$3 WHERE project=$4 AND source=$5 AND content_id=$6
        """,
        text,
        hash_text(text),
        embedding_str,
        project,
        source,
        content_id,
    )
