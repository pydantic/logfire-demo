import re

import asyncpg
import logfire
from httpx import AsyncClient
from openai import AsyncOpenAI

from ..common.embeddings import (
    EmbeddingsSource,
    create_embeddings,
    delete_embeddings_by_hash,
    generate_embedding,
    get_stored_embeddings_hash_by_source,
    hash_text,
)


async def get_content(client: AsyncClient, url: str) -> str:
    with logfire.span('Reading from {url=}', url=url):
        r = await client.get(url)
        r.raise_for_status()
        return r.content.decode()


def split_markdown_sections(content: str) -> list[dict[str, str]]:
    """Splits a Markdown file into sections based on headers."""
    # Match Markdown headers (#, ##, ### etc.)
    pattern = r'^(#{1,6})\s+(.*)$'
    matches = re.finditer(pattern, content, re.MULTILINE)

    sections = []
    last_index = 0

    for match in matches:
        header, title = match.groups()
        start = match.start()

        # Extract previous section content
        if sections:
            sections[-1]['content'] = content[last_index:start].strip()

        sections.append(
            {
                'level': len(header),  # Header level (# = 1, ## = 2)
                'title': title.strip(),
                'content': '',
            }
        )
        last_index = start

    # Add the last section content
    if sections:
        sections[-1]['content'] = content[last_index:].strip()

    return sections


async def update_docs_embeddings(
    client: AsyncClient, pg_pool: asyncpg.Pool, openai_client: AsyncOpenAI, url: str, source: EmbeddingsSource
) -> None:
    content = await get_content(client, url)
    sections = split_markdown_sections(content)

    async with pg_pool.acquire() as conn:
        hashes: set[str] = set()
        stored_hashes = await get_stored_embeddings_hash_by_source(conn, source)

        for section in sections:
            try:
                section_content = f'{section["title"]} {section["content"]}'
                embeddings = await generate_embedding(openai_client, section_content)
                text_hash = hash_text(section_content)
                hashes.add(text_hash)
                if text_hash in stored_hashes:
                    logfire.info('Skipping {text_hash=}', text_hash=text_hash)
                    continue
                await create_embeddings(
                    conn,
                    source='pydantic_ai_docs',
                    text=section_content,
                    text_hash=text_hash,
                    embedding=embeddings,
                )
            except Exception as exc:
                logfire.error('Failed to update docs embeddings {exc!r}', exc=exc)

        # Remove old embeddings that are not in the new content
        hashes_to_delete = stored_hashes - hashes
        if hashes_to_delete:
            await delete_embeddings_by_hash(conn, hashes_to_delete, source)
