from datetime import datetime

from asyncpg import Connection


async def create_slack_message(
    conn: Connection,
    channel: str,
    author: str,
    message_id: str,
    event_ts: str,
    parent_event_ts: str | None,
    text: str,
    ts: datetime,
    embedding: list[list[float]],
) -> None:
    """Create a new slack message in the database"""
    embedding_str = '[' + ','.join(map(str, embedding)) + ']'
    await conn.execute(
        """
        INSERT INTO slack_messages (channel, author, message_id, event_ts, parent_event_ts, text, ts, embedding)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
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
