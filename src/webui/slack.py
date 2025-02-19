from fastapi import APIRouter, Request
from fastui import FastUI, events
from fastui import components as c

from ..common.db import Database
from ..common.db.slack import get_root_slack_messages, get_slack_thread
from .shared import demo_page

router = APIRouter()


@router.get('', response_model=FastUI, response_model_exclude_none=True)
async def read_messages(request: Request, db: Database):
    async with db.acquire() as conn:
        messages = await get_root_slack_messages(conn)

        text = ''
        for msg in messages:
            text += f'- **@{msg["author"]}** ({msg["ts"]}): _{msg["text"][:50]}_ - [View Thread ({msg["replies_count"]})](/slack/thread/{msg["id"]}) \n\n'

        return demo_page(
            c.Link(components=[c.Text(text='back')], on_click=events.BackEvent()),
            c.Div(components=[c.Markdown(text=text)]),
            title='Logfire Slack Messages',
        )


@router.get('/thread/{message_id}', response_model=FastUI, response_model_exclude_none=True)
async def read_thread(request: Request, db: Database, message_id: int):
    async with db.acquire() as conn:
        messages = await get_slack_thread(conn, message_id)

        text = ''
        for i, msg in enumerate(messages):
            text += f'{i + 1}. **@{msg["author"]}** ({msg["ts"]}): _{msg["text"]}_ \n\n'
        return demo_page(
            c.Link(components=[c.Text(text='back')], on_click=events.BackEvent()),
            c.Div(components=[c.Markdown(text=text)], class_name='col-md-6'),
            title=f'Logfire Slack Messages Thread {message_id}',
        )
