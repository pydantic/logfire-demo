from __future__ import annotations as _annotations

import asyncio
import base64
import json
import re
from typing import Annotated

from fastapi import APIRouter, HTTPException
from fastui import AnyComponent, FastUI, events
from fastui import components as c
from fastui.forms import fastui_form
from starlette.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from ..common import ArqRedisDep
from ..common.db import Database
from .shared import demo_page

router = APIRouter()


class RepoForm(BaseModel):
    repo: str = Field(
        json_schema_extra={'placeholder': '{org}/{repo}'},
        title='GitHub repository',
        description='In the format "{owner}/{repo}", or the repo URL.',
    )

    @field_validator('repo')
    def validate_repo(cls, v: str) -> str:
        own_repo_re = r'[A-Za-z0-9\-_]+/[A-Za-z0-9\-_]+'
        if re.fullmatch(own_repo_re, v):
            return v
        elif m := re.fullmatch(rf'https://github\.com/({own_repo_re})', v):
            return m.group(1)
        else:
            raise ValueError('Invalid repo format')


@router.get('', response_model=FastUI, response_model_exclude_none=True)
def worker() -> list[AnyComponent]:
    md = 'Enter a GitHub repository, the worker will then download each file and count lines of code.'
    return demo_page(
        c.Link(components=[c.Text(text='back')], on_click=events.BackEvent()),
        c.Markdown(text=md),
        c.ModelForm(model=RepoForm, display_mode='page', submit_url='/api/worker/start'),
        title='CLOC Worker',
    )


@router.post('/start', response_model=FastUI, response_model_exclude_none=True)
async def start_worker(
    db: Database, arq_redis: ArqRedisDep, repo: Annotated[RepoForm, fastui_form(RepoForm)]
) -> list[AnyComponent]:
    async with db.acquire() as con:
        await con.execute(
            """
            INSERT INTO repo_clocs (repo, status) VALUES ($1, 'queued')
            ON CONFLICT (repo) DO NOTHING
            """,
            repo.repo,
        )
    await arq_redis.enqueue_job('cloc', repo.repo)

    repo_base64 = base64.urlsafe_b64encode(repo.repo.encode()).decode()
    return [c.ServerLoad(path=f'/worker/wait/{repo_base64}', sse=True)]


@router.get('/wait/{repo_base64}')
async def wait_on_task(db: Database, repo_base64: str) -> StreamingResponse:
    repo = base64.urlsafe_b64decode(repo_base64).decode()

    async def stream():
        m = FastUI(root=[c.Spinner(text='Running...')])
        yield f'data: {m.model_dump_json(by_alias=True, exclude_none=True)}\n\n'

        while True:
            async with db.acquire() as con:
                status = await con.fetchval('SELECT status FROM repo_clocs WHERE repo = $1', repo)

            match status:
                case None:
                    raise HTTPException(status_code=404, detail='Task not found')
                case 'done' | 'error':
                    m = FastUI(root=[c.FireEvent(event=events.GoToEvent(url=f'/worker/result/{repo_base64}'))])
                    yield f'data: {m.model_dump_json(by_alias=True, exclude_none=True)}\n\n'
                    break
                case 'queued':
                    await asyncio.sleep(0.5)
                case _:
                    raise ValueError(f'Invalid status: {status}')

    return StreamingResponse(stream(), media_type='text/event-stream')


class LineOfCode(BaseModel):
    language: str
    loc: int = Field(title='Lines of code')


@router.get('/result/{repo_base64}', response_model=FastUI, response_model_exclude_none=True)
async def result(db: Database, repo_base64: str) -> list[AnyComponent]:
    repo = base64.urlsafe_b64decode(repo_base64).decode()
    async with db.acquire() as con:
        status, code_counts = await con.fetchrow('SELECT status, counts FROM repo_clocs WHERE repo = $1', repo)

    if status == 'done':
        rows = [LineOfCode(language=k, loc=v) for k, v in json.loads(code_counts).items()]
        rows.sort(key=lambda x: x.loc, reverse=True)
        return demo_page(
            c.Link(components=[c.Text(text='back')], on_click=events.BackEvent()),
            c.Markdown(text=f'## Results for `{repo}`'),
            c.Table(data=rows, data_model=LineOfCode),
            title='Line of Code',
        )
    else:
        return demo_page(
            c.Link(components=[c.Text(text='back')], on_click=events.BackEvent()),
            c.Error(title='Error', description='An error occurred while processing the task.'),
            title='Line of Code',
        )
