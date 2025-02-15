from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..common.db import Database
from ..common.db.slack import get_root_slack_messages, get_slack_thread

router = APIRouter()


# Initialize templates directory
templates = Jinja2Templates(directory='src/webui/templates/slack/')


@router.get('', response_class=HTMLResponse)
async def read_messages(request: Request, db: Database):
    async with db.acquire() as conn:
        messages = await get_root_slack_messages(conn)
        return templates.TemplateResponse('index.html', {'request': request, 'messages': messages})


@router.get('/thread/{message_id}', response_class=HTMLResponse)
async def read_thread(request: Request, db: Database, message_id: int):
    async with db.acquire() as conn:
        messages = await get_slack_thread(conn, message_id)
        return templates.TemplateResponse('thread.html', {'request': request, 'messages': messages})
