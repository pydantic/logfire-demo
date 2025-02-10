import re

import asyncpg
import logfire
import tiktoken
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

TOKEN_LIMIT = 8192  # OpenAI embedding model token limit


async def get_content(client: AsyncClient, url: str) -> str:
    with logfire.span('Reading from {url=}', url=url):
        r = await client.get(url)
        r.raise_for_status()
        return r.content.decode()


def count_tokens(text: str, model: str = 'gpt-3.5-turbo') -> int:
    """Counts the number of tokens in a given text using OpenAI's tiktoken."""
    encoding = tiktoken.encoding_for_model(model)
    return len(encoding.encode(text))


def split_large_text(text: str, max_tokens: int = TOKEN_LIMIT) -> list[str]:
    """Splits text into smaller chunks by paragraph if it exceeds max_tokens."""
    paragraphs = text.split('\n\n')  # Split by double newlines (paragraphs)
    chunks = []
    current_chunk = []

    for paragraph in paragraphs:
        current_chunk.append(paragraph)
        chunk_text = '\n\n'.join(current_chunk)

        if count_tokens(chunk_text) > max_tokens:
            # Remove the last added paragraph and store the chunk
            current_chunk.pop()
            chunks.append('\n\n'.join(current_chunk))
            current_chunk = [paragraph]  # Start new chunk

    # Add remaining content
    if current_chunk:
        chunks.append('\n\n'.join(current_chunk))

    return chunks


def split_markdown_sections(content: str) -> list[dict[str, str]]:
    """Splits a Markdown file into sections based on headers, ensuring each section is <= 8192 tokens."""
    pattern = r'^(#{1,6})\s+(.*)$'
    matches = re.finditer(pattern, content, re.MULTILINE)

    sections = []
    last_index = 0

    for match in matches:
        header, title = match.groups()
        start = match.start()

        if sections:
            section_content = content[last_index:start].strip()
            # Split if content exceeds token limit
            if count_tokens(section_content) > TOKEN_LIMIT:
                section_chunks = split_large_text(section_content, TOKEN_LIMIT)
                for chunk in section_chunks:
                    sections.append(
                        {
                            'level': sections[-1]['level'],
                            'title': sections[-1]['title'],
                            'content': chunk,
                        }
                    )
            else:
                sections[-1]['content'] = section_content

        sections.append({'level': len(header), 'title': title.strip(), 'content': ''})
        last_index = start

    # Process the last section
    if sections:
        last_content = content[last_index:].strip()
        if count_tokens(last_content) > TOKEN_LIMIT:
            section_chunks = split_large_text(last_content, TOKEN_LIMIT)
            for chunk in section_chunks:
                sections.append(
                    {
                        'level': sections[-1]['level'],
                        'title': sections[-1]['title'],
                        'content': chunk,
                    }
                )
        else:
            sections[-1]['content'] = last_content

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
                text_hash = hash_text(section_content)
                hashes.add(text_hash)
                if text_hash in stored_hashes:
                    logfire.info('Skipping {text_hash=}', text_hash=text_hash)
                    continue
                embeddings = await generate_embedding(openai_client, section_content)
                await create_embeddings(
                    conn,
                    source=source,
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
