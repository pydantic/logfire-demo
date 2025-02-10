import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Annotated

import logfire
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from openai import AsyncOpenAI

from ..common.db import Database
from ..common.embeddings import create_embeddings, generate_embedding, hash_text
from .settings import settings

router = APIRouter()


def _get_openai_client(request: Request) -> AsyncOpenAI:
    return request.app.state.openai_client


AsyncOpenAIClientDep = Annotated[AsyncOpenAI, Depends(_get_openai_client)]


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
        logfire.debug('Event not supported: {event_type}', event_type=event_type)
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
            logfire.debug('Action not supported: {data}', data=data)
            return {'message': 'Action not supported'}
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
            logfire.debug('Action not supported: {data}', data=data)
            return {'message': 'Action not supported'}

    if not author or not text or not external_reference:
        logfire.error('Invalid GitHub issue: {data}', data=data)
        return {'message': 'Invalid issue'}

    embedding = await generate_embedding(openai_client, text)

    async with db.acquire_trans() as conn:
        await create_embeddings(
            conn,
            source='github_issue',
            external_reference=external_reference,
            text=text,
            text_hash=hash_text(text),
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
                await create_embeddings(
                    conn,
                    source='slack_message',
                    external_reference=external_reference,
                    text=text,
                    text_hash=hash_text(text),
                    author=author,
                    event_ts=event_ts,
                    embedding=embedding,
                    parent=parent,
                )

            logfire.info('Saved Slack message: {external_reference}', external_reference=external_reference)

    return {'message': 'Event received'}
