import urllib.parse
from typing import Annotated, AsyncIterable

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
from ..common import AsyncClientDep

router = APIRouter()


class PromptModel(BaseModel):
    prompt: str | None = Field(title='Prompt', description='Ask me (almost) anything', max_length=300)


form_comp = c.ModelForm(
    model=PromptModel,
    method='POST',
    submit_url='/api/llm/ask',
    footer=[c.Div(components=[c.Button(text='Ask')], class_name='text-end')],
)


@router.get('', response_model=FastUI, response_model_exclude_none=True)
async def llm_page() -> list[AnyComponent]:
    return demo_page(
        c.Div(
            components=[c.Div(components=[form_comp], class_name='col-md-6')],
            class_name='row justify-content-center',
        ),
    )


@router.post('/ask', response_model=FastUI, response_model_exclude_none=True)
async def llm_ask(prompt: Annotated[PromptModel, fastui_form(PromptModel)]) -> list[AnyComponent]:
    return [
        c.Markdown(text=f'**You asked:** {prompt.prompt}'),
        c.ServerLoad(path=f'/llm/ask/stream?prompt={urllib.parse.quote(prompt.prompt)}', sse=True),
        form_comp,
    ]


async def _llm_stream_gen(http_client: AsyncClientDep, prompt: str) -> AsyncIterable[str]:
    messages = [
        {'role': 'system', 'content': 'please response in markdown only.'},
        {'role': 'user', 'content': prompt},
    ]
    model = 'gpt-4'
    with logfire.span('openai {model=} {messages=}', model=model, messages=messages) as logfire_span:
        chunks = await AsyncOpenAI(http_client=http_client).chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
        )

        output = ''
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
        logfire_span.set_attribute('usage', len(tiktoken.encoding_for_model(model).encode(output)))


@router.get('/ask/stream', response_model=FastUI, response_model_exclude_none=True)
async def llm_stream(http_client: AsyncClientDep, prompt: str) -> StreamingResponse:
    return StreamingResponse(_llm_stream_gen(http_client, prompt), media_type='text/event-stream')
