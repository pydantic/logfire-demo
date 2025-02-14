import json
from datetime import datetime
from typing import Any, Literal

from asyncpg import Connection

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
        INSERT INTO github_contents (project, source, content_id, external_reference, text, event_ts, embedding)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        project,
        source,
        content_id,
        external_reference,
        text,
        event_ts,
        embedding_str,
    )


async def get_github_content(
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
        UPDATE github_contents SET text=$1, embedding=$2 WHERE project=$3 AND source=$4 AND content_id=$5
        """,
        text,
        embedding_str,
        project,
        source,
        content_id,
    )


async def fetch_issues_for_similarity_check(conn: Connection) -> list[dict[str, Any]]:
    """Fetch GitHub issues for similarity check."""
    return await conn.fetch(
        """
        SELECT
            id,
            project,
            text,
            external_reference
        FROM github_contents
        WHERE source='issue' AND similar_issues IS NULL
        """,
    )


async def find_similar_issues(conn: Connection, id: int, project: GithubContentProject) -> list[dict[str, Any]]:
    """Find similar GitHub issues by vector similarity."""
    return await conn.fetch(
        """
        SELECT
            text,
            external_reference,
            embedding <=> (SELECT embedding FROM github_contents WHERE id = $1) AS distance
        FROM github_contents
        WHERE source='issue' AND project=$2 AND id != $3
        ORDER BY distance
        LIMIT 3;
        """,
        id,
        project,
        id,
    )


async def update_similar_issues(conn: Connection, id: int, similar_issues_obj: list[dict[str, Any]]) -> None:
    await conn.execute(
        """
        UPDATE github_contents SET similar_issues=$1 WHERE id=$2
        """,
        json.dumps(similar_issues_obj),
        id,
    )
