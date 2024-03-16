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
async def llm_ask(db: Database, prompt: Annotated[PromptModel, fastui_form(PromptModel)], chat_id: UUID) -> list[AnyComponent]:
    async with db.acquire() as conn:
        # create a new message row
        # TODO check total daily cost
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


@router.get('/ask/stream', response_model=FastUI, response_model_exclude_none=True)
async def llm_stream(db: Database, http_client: AsyncClientDep, chat_id: UUID) -> StreamingResponse:
    async with db.acquire() as conn:
        # get messages from this chat
        chat_messages = await conn.fetch(
            'select role, message as content from messages where chat_id = $1 order by created_at',
            chat_id,
        )

    async def gen() -> AsyncIterable[str]:
        messages = [{'role': 'system', 'content': 'please response in markdown only.'}, *map(dict, chat_messages)]
        model = 'gpt-4'
        output = ''
        usage = None
        try:
            with logfire.span('openai {model=} {messages=}', model=model, messages=messages) as logfire_span:
                chunks = await AsyncOpenAI(http_client=http_client).chat.completions.create(
                    model=model,
                    messages=messages,
                    stream=True,
                )

                chunk_count = 0
                async for chunk in chunks:
                    text = chunk.choices[0].delta.content
                    chunk_count += 1
                    if text is not None:
                        output += text
                        m = FastUI(root=[c.Markdown(text=f'**{model.upper()}**:\n\n{output}')])
                        yield f'data: {m.model_dump_json(by_alias=True, exclude_none=True)}\n\n'
                logfire_span.set_attribute('chunk_count', chunk_count)
                logfire_span.set_attribute('output', output)
                usage = len(tiktoken.encoding_for_model(model).encode(output))
                logfire_span.set_attribute('usage', usage)
        finally:
            async with db.acquire() as conn:
                await conn.execute(
                    """
                    insert into messages (chat_id, role, message, cost) VALUES ($1, 'system', $2, $3)
                    """,
                    chat_id,
                    output,
                    usage,
                )

    return StreamingResponse(gen(), media_type='text/event-stream')
