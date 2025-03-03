from datetime import datetime
from typing import Any

from asyncpg import Connection


async def create_slack_message(
    conn: Connection[Any],
    channel: str,
    author: str,
    message_id: str,
    event_ts: str,
    parent_event_ts: str | None,
    text: str,
    ts: datetime,
    embedding: list[float],
) -> None:
    """Create a new slack message in the database"""
    embedding_str = '[' + ','.join(map(str, embedding)) + ']'
    await conn.execute(
        """
        INSERT INTO slack_messages (channel, author, message_id, event_ts, parent_event_ts, text, ts, embedding)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        channel,
        author,
        message_id,
        event_ts,
        parent_event_ts,
        text,
        ts,
        embedding_str,
    )


async def get_root_slack_messages(conn: Connection[Any], limit: int = 10) -> list[dict[str, Any]]:
    """Fetch the root slack message from the database."""
    return await conn.fetch(
        """
        WITH messages AS (
            SELECT s.id, s.author, s.text, s.ts, count(r.id) as replies_count
            FROM slack_messages s
            LEFT JOIN slack_messages r ON r.parent_event_ts = s.event_ts OR r.event_ts = s.event_ts
            WHERE s.parent_event_ts IS NULL
            GROUP BY s.author, s.id, s.text, s.ts, s.event_ts
            ORDER BY s.ts DESC
            LIMIT $1
        )
        SELECT * FROM messages ORDER BY ts
        """,
        limit,
    )


async def get_slack_thread(conn: Connection[Any], message_id: int) -> list[dict[str, Any]]:
    """Fetch a slack thread from the database."""
    return await conn.fetch(
        """
        SELECT author, text, ts
        FROM slack_messages WHERE parent_event_ts=(SELECT event_ts FROM slack_messages WHERE id = $1)
        ORDER BY ts
        """,
        message_id,
    )
