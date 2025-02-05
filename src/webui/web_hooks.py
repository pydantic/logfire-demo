import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Annotated, Literal

import logfire
from asyncpg import Connection
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from openai import AsyncOpenAI

from ..common.db import Database
from .settings import settings

router = APIRouter()


def _get_openai_client(request: Request) -> AsyncOpenAI:
    return request.app.state.openai_client


AsyncOpenAIClientDep = Annotated[AsyncOpenAI, Depends(_get_openai_client)]


ConversationSource = Literal['slack_message', 'github_issue']


async def create_conversation(
    conn: Connection,
    source: ConversationSource,
    external_reference: str,
    text: str,
    author: str,
    event_ts: datetime,
    embedding: list[list[float]],
    parent: str | None = None,
) -> None:
    """Create a new conversation in the database"""
    embedding_str = '[' + ','.join(map(str, embedding)) + ']'
    await conn.execute(
        """
        INSERT INTO conversations (source, external_reference, text, author, event_ts, embedding, parent)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        source,
        external_reference,
        text,
        author,
        event_ts,
        embedding_str,
        parent,
    )


async def generate_embedding(openai_client: AsyncOpenAI, text: str) -> list[float]:
    with logfire.span('call openai'):
        response = await openai_client.embeddings.create(input=text, model='text-embedding-ada-002')
        return response.data[0].embedding


def verify_github_signature(secret: str, payload: bytes, signature: str) -> bool:
    """Verify GitHub webhook signature (HMAC SHA-256)"""
    mac = hmac.new(secret.encode(), msg=payload, digestmod=hashlib.sha256)
    expected_signature = f'sha256={mac.hexdigest()}'
    return hmac.compare_digest(expected_signature, signature)


@router.post('/github')
async def github_webhook(
    request: Request,
    db: Database,
    openai_client: AsyncOpenAIClientDep,
    x_hub_signature_256: str = Header(None),  # GitHub sends signature in headers
):
    """Handle GitHub webhook events"""
    payload = await request.body()

    # Verify signature for security
    if not verify_github_signature(settings.github_webhook_secret.get_secret_value(), payload, x_hub_signature_256):
        raise HTTPException(status_code=403, detail='Invalid signature')

    data = await request.json()  # Convert request payload to JSON
    event_type = request.headers.get('X-GitHub-Event')  # GitHub event type

    if event_type not in ['issues', 'issue_comment']:
        return {'message': 'Event not supported'}

    if event_type == 'issues':
        logfire.info('Received GitHub issue event: {data}', data=data)
        if data.get('action') == 'opened':
            issue = data.get('issue')
            if not issue:
                logfire.error('Invalid GitHub issue: {data}', data=data)
                return {'message': 'Invalid issue'}

            author = issue.get('user', {}).get('login')
            text = issue.get('body')
            external_reference = issue.get('html_url')
            event_ts = datetime.fromisoformat(issue.get('created_at').replace('Z', '+00:00'))
            parent = None
        else:
            return {'message': 'Event not supported'}
    elif event_type == 'issue_comment':
        logfire.info('Received GitHub comment event: {data}', data=data)
        if data.get('action') == 'created':
            issue = data.get('issue')
            comment = data.get('comment')
            if not issue or not comment or 'pull_request' in issue:  # Ignore pull requests comments
                logfire.error('Invalid GitHub comment: {data}', data=data)
                return {'message': 'Invalid comment'}

            author = comment.get('user', {}).get('login')
            text = comment.get('body')
            external_reference = comment.get('html_url')
            event_ts = datetime.fromisoformat(comment.get('created_at').replace('Z', '+00:00'))
            parent = issue.get('html_url')
        else:
            return {'message': 'Event not supported'}

    if not author or not text or not external_reference:
        logfire.error('Invalid GitHub issue: {data}', data=data)
        return {'message': 'Invalid issue'}

    embedding = await generate_embedding(openai_client, text)

    async with db.acquire_trans() as conn:
        await create_conversation(
            conn,
            source='github_issue',
            external_reference=external_reference,
            text=text,
            author=author,
            event_ts=event_ts,
            embedding=embedding,
            parent=parent,
        )
        logfire.info('Saved GitHub issue: {external_reference}', external_reference=external_reference)

    return {'message': 'Webhook received successfully!'}


def verify_slack_signature(request: Request, body: bytes, slack_signing_secret: str) -> bool:
    """Verify Slack request signature for security"""
    timestamp = request.headers.get('X-Slack-Request-Timestamp')
    slack_signature = request.headers.get('X-Slack-Signature')

    if not timestamp or not slack_signature:
        return False

    # Slack signature format: v0=HMAC_SHA256(secret, "v0:{timestamp}:{body}")
    basestring = f'v0:{timestamp}:{body.decode("utf-8")}'
    calculated_signature = (
        'v0=' + hmac.new(slack_signing_secret.encode(), basestring.encode(), hashlib.sha256).hexdigest()
    )

    return hmac.compare_digest(calculated_signature, slack_signature)


@router.post('/slack/events')
async def slack_events(request: Request, db: Database, openai_client: AsyncOpenAIClientDep):
    """Receive Slack messages via webhook"""
    body = await request.body()
    if not verify_slack_signature(request, body, settings.slack_signing_secret.get_secret_value()):
        raise HTTPException(status_code=403, detail='Invalid signature')

    data = json.loads(body)
    if data.get('type') == 'url_verification':
        # Slack sends a challenge code for verification
        return {'challenge': data['challenge']}

    if data.get('type') == 'event_callback':
        event = data.get('event', {})

        logfire.info('Received Slack event: {event}', event=event)

        # Only process messages from allowed channels
        if event.get('channel') not in settings.slack_channel_ids:
            logfire.error('Invalid Slack channel: {channel}', channel=event.get('channel'))
            return {'message': 'Invalid channel'}

        if event.get('type') == 'message' and event.get('subtype') is None:
            author = event.get('user')
            text = event.get('text')
            external_reference = event.get('client_msg_id')
            event_ts = datetime.fromtimestamp(float(event.get('event_ts')), tz=UTC)
            if not author or not text or not external_reference:
                logfire.error('Invalid Slack message: {event}', event=event)
                return {'message': 'Invalid event'}
            parent = None
            if thread_ts := event.get('thread_ts'):
                parent = datetime.fromtimestamp(float(thread_ts), tz=UTC).isoformat()

            embedding = await generate_embedding(openai_client, text)

            async with db.acquire_trans() as conn:
                await create_conversation(
                    conn,
                    source='slack_message',
                    external_reference=external_reference,
                    text=text,
                    author=author,
                    event_ts=event_ts,
                    embedding=embedding,
                    parent=parent,
                )

            logfire.info('Saved Slack message: {external_reference}', external_reference=external_reference)

    return {'message': 'Event received'}
