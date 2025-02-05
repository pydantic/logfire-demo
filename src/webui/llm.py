import asyncio
import hashlib
import json
from collections.abc import AsyncIterable
from random import random
from typing import Annotated
from uuid import UUID

import logfire
import tiktoken
from fastapi import APIRouter
from fastui import AnyComponent, FastUI, events
from fastui import components as c
from fastui.forms import fastui_form
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from ..common import AsyncClientDep
from ..common.db import Database
from .shared import demo_page

router = APIRouter()


class PromptModel(BaseModel):
    prompt: str | None = Field(title='Prompt', description='Ask me (almost) anything', max_length=300)


def form_comp(chat_id: UUID) -> c.ModelForm:
    return c.ModelForm(
        model=PromptModel,
        method='POST',
        submit_url=f'/api/llm/ask/{chat_id}',
        footer=[c.Div(components=[c.Button(text='Ask')], class_name='text-end')],
    )


@router.get('', response_model=FastUI, response_model_exclude_none=True)
async def llm_page(db: Database) -> list[AnyComponent]:
    async with db.acquire() as conn:
        # create a new chat row
        chat_id = await conn.fetchval('insert into chats DEFAULT VALUES RETURNING id')

    return demo_page(
        c.Link(components=[c.Text(text='back')], on_click=events.BackEvent()),
        c.Div(
            components=[c.Div(components=[form_comp(chat_id)], class_name='col-md-6')],
            class_name='row justify-content-center',
        ),
        title='LLM Query',
    )


@router.post('/ask/{chat_id}', response_model=FastUI, response_model_exclude_none=True)
async def llm_ask(
    db: Database, prompt: Annotated[PromptModel, fastui_form(PromptModel)], chat_id: UUID
) -> list[AnyComponent]:
    async with db.acquire() as conn:
        # create a new message row
        await conn.execute(
            """
            insert into messages (chat_id, role, message) VALUES ($1, 'user', $2)
            """,
            chat_id,
            prompt.prompt,
        )
    return [
        c.Markdown(text=f'**You asked:** {prompt.prompt}'),
        c.ServerLoad(path=f'/llm/ask/stream/{chat_id}', sse=True),
        form_comp(chat_id),
    ]


OPENAI_MODEL = 'gpt-4'


@router.get('/ask/stream/{chat_id}')
async def llm_stream(db: Database, http_client: AsyncClientDep, chat_id: UUID) -> StreamingResponse:
    async with db.acquire() as conn:
        # count tokens used today
        tokens_used = await conn.fetchval(
            'select sum(cost) from messages where created_at > current_date and cost is not null'
        )
        logfire.info('{cost_today=}', cost_today=tokens_used)

        if tokens_used is not None and tokens_used > 500_000:
            content = [_sse_message('**Limit Exceeded**:\n\nDaily token limit exceeded.')]
            return StreamingResponse(content, media_type='text/event-stream')

        # get messages from this chat
        chat_messages = await conn.fetch(
            'select role, message as content from messages where chat_id = $1 order by created_at',
            chat_id,
        )

        questions = '|'.join(m['content'].lower() for m in chat_messages if m['role'] == 'user')
        questions_hash = hashlib.md5(questions.encode()).hexdigest()

        opt_chunks = await conn.fetchval('select chunks from llm_results where questions_hash = $1', questions_hash)

    messages = [{'role': 'system', 'content': 'Please response in markdown only.'}, *map(dict, chat_messages)]

    async def gen_saved(chunks_json: str) -> AsyncIterable[str]:
        """
        Generate a result based on on previously saved chunks.
        """
        chunks = json.loads(chunks_json)
        output = ''
        try:
            await asyncio.sleep(0.5 + random() * 0.5)
            with logfire.span('saved result {messages=}', messages=messages) as logfire_span:
                for chunk in chunks:
                    if chunk is not None:
                        output += chunk
                        yield _sse_message(f'**{OPENAI_MODEL.upper()}s**:\n\n{output}')

                    # 0.12s delay is taken roughly from
                    # https://github.com/pydantic/FastUI/blob/196414360b69b3dab7012576f852229831307883/demo/sse.py#L66C1-L388C2
                    await asyncio.sleep(random() * 0.12)
                logfire_span.set_attribute('output', output)
        finally:
            async with db.acquire() as conn:
                await conn.execute(
                    "insert into messages (chat_id, role, message, cost) VALUES ($1, 'system', $2, 0)",
                    chat_id,
                    output,
                )

    async def gen_openai() -> AsyncIterable[str]:
        output = ''
        input_usage = sum(_count_usage(m['content']) for m in messages if m['role'] in ('system', 'user'))
        output_usage = 0
        output_chunks = []
        try:
            openai_client = AsyncOpenAI(http_client=http_client)
            logfire.instrument_openai(openai_client=openai_client)
            with logfire.span('call openai'):
                chunks = await openai_client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=messages,
                    stream=True,
                    stream_options={'include_usage': True},
                )

                async for chunk in chunks:
                    text = chunk.choices[0].delta.content
                    output_chunks.append(text)
                    if text is not None:
                        output += text
                        yield _sse_message(f'**{OPENAI_MODEL.upper()}**:\n\n{output}')
                output_usage = _count_usage(output)
            async with db.acquire() as conn:
                await conn.execute(
                    'insert into llm_results (questions_hash, chunks) VALUES ($1, $2) ON CONFLICT DO NOTHING',
                    questions_hash,
                    json.dumps(output_chunks),
                )
        finally:
            async with db.acquire() as conn:
                await conn.execute(
                    "insert into messages (chat_id, role, message, cost) VALUES ($1, 'system', $2, $3)",
                    chat_id,
                    output,
                    input_usage + output_usage,
                )

    if opt_chunks:
        gen = gen_saved(opt_chunks)
    else:
        gen = gen_openai()
    return StreamingResponse(gen, media_type='text/event-stream')


TOKEN_ENCODER = tiktoken.encoding_for_model(OPENAI_MODEL)


def _count_usage(message: str) -> int:
    return len(TOKEN_ENCODER.encode(message))


def _sse_message(markdown: str) -> str:
    m = FastUI(root=[c.Markdown(text=markdown)])
    return f'data: {m.model_dump_json(by_alias=True, exclude_none=True)}\n\n'
