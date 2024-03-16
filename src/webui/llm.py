import urllib.parse
from typing import Annotated, AsyncIterable
from uuid import UUID

import logfire
from fastapi import APIRouter
from fastui import AnyComponent, FastUI
from fastui.forms import fastui_form
from fastui import components as c
from starlette.responses import StreamingResponse
from pydantic import BaseModel, Field
from openai import AsyncOpenAI
import tiktoken

from .shared import demo_page
from ..common import AsyncClientDep, build_params
from ..common.db import Database

router = APIRouter()


class PromptModel(BaseModel):
    prompt: str | None = Field(title='Prompt', description='Ask me (almost) anything', max_length=300)


def form_comp(chat_id: UUID) -> c.ModelForm:
    return c.ModelForm(
        model=PromptModel,
        method='POST',
        submit_url=f'/api/llm/ask?{build_params(chat_id=chat_id)}',
        footer=[c.Div(components=[c.Button(text='Ask')], class_name='text-end')],
    )


@router.get('', response_model=FastUI, response_model_exclude_none=True)
async def llm_page(db: Database) -> list[AnyComponent]:
    async with db.acquire() as conn:
        # create a new chat row
        chat_id = await conn.fetchval('insert into chats DEFAULT VALUES RETURNING id')
    return demo_page(
        c.Div(
            components=[c.Div(components=[form_comp(chat_id)], class_name='col-md-6')],
            class_name='row justify-content-center',
        ),
    )


@router.post('/ask', response_model=FastUI, response_model_exclude_none=True)
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
        c.ServerLoad(path=f'/llm/ask/stream?{build_params(chat_id=chat_id)}', sse=True),
        form_comp(chat_id),
    ]


OPENAI_MODEL = 'gpt-4'


@router.get('/ask/stream', response_model=FastUI, response_model_exclude_none=True)
async def llm_stream(db: Database, http_client: AsyncClientDep, chat_id: UUID) -> StreamingResponse:
    async with db.acquire() as conn:
        # count tokens used today
        tokens_used = await conn.fetchval(
            'select sum(cost) from messages where created_at > current_date and cost is not null'
        )
        logfire.info('{cost_today=}', cost_today=tokens_used)

        # 1m tokens is $10 if I've done my math right
        if tokens_used is not None and tokens_used > 1_000_000:
            content = [_sse_message(f'**Limit Exceeded**:\n\nDaily token limit exceeded.')]
            return StreamingResponse(content, media_type='text/event-stream')

        # get messages from this chat
        chat_messages = await conn.fetch(
            'select role, message as content from messages where chat_id = $1 order by created_at',
            chat_id,
        )

    async def gen() -> AsyncIterable[str]:
        messages = [{'role': 'system', 'content': 'Please response in markdown only.'}, *map(dict, chat_messages)]
        output = ''
        input_usage = sum(_count_usage(m['content']) for m in messages if m['role'] in ('system', 'user'))
        output_usage = 0
        try:
            with logfire.span('openai {model=} {messages=}', model=OPENAI_MODEL, messages=messages) as logfire_span:
                chunks = await AsyncOpenAI(http_client=http_client).chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=messages,
                    stream=True,
                )

                chunk_count = 0
                async for chunk in chunks:
                    text = chunk.choices[0].delta.content
                    chunk_count += 1
                    if text is not None:
                        output += text
                        yield _sse_message(f'**{OPENAI_MODEL.upper()}**:\n\n{output}')
                logfire_span.set_attribute('chunk_count', chunk_count)
                logfire_span.set_attribute('output', output)
                logfire_span.set_attribute('input_usage', input_usage)
                output_usage = _count_usage(output)
                logfire_span.set_attribute('output_usage', output_usage)
        finally:
            async with db.acquire() as conn:
                await conn.execute(
                    """
                    insert into messages (chat_id, role, message, cost) VALUES ($1, 'system', $2, $3)
                    """,
                    chat_id,
                    output,
                    input_usage + output_usage,
                )

    return StreamingResponse(gen(), media_type='text/event-stream')


TOKEN_ENCODER = tiktoken.encoding_for_model(OPENAI_MODEL)


def _count_usage(message: str) -> int:
    return len(TOKEN_ENCODER.encode(message))


def _sse_message(markdown: str) -> str:
    m = FastUI(root=[c.Markdown(text=markdown)])
    return f'data: {m.model_dump_json(by_alias=True, exclude_none=True)}\n\n'
