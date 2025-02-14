import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Annotated, Any

import logfire
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from openai import AsyncOpenAI

from ..common.db import Database
from ..common.db.github import create_github_content, get_github_content, update_github_content
from ..common.db.slack import create_slack_message
from ..common.embeddings import generate_embedding, truncate_text_to_token_limit
from .settings import settings

router = APIRouter()


def _get_openai_client(request: Request) -> AsyncOpenAI:
    return request.app.state.openai_client


AsyncOpenAIClientDep = Annotated[AsyncOpenAI, Depends(_get_openai_client)]


async def generate_github_content_embedding(openai_client: AsyncOpenAI, text: str) -> list[list[float]]:
    """Generate an embedding for GitHub content."""
    truncated_text = truncate_text_to_token_limit(text)
    return await generate_embedding(openai_client, truncated_text)


def extract_data(issue: dict[str, Any]) -> tuple[int, str, str, datetime]:
    """Extract relevant information from a GitHub issue or comment."""
    issue_id = issue.get('id')
    title = issue.get('title')
    text = issue.get('body')
    if title:
        text = f'{title}\n\n{text}'
    external_reference = issue.get('html_url')
    event_ts = datetime.fromisoformat(issue.get('created_at').replace('Z', '+00:00'))
    return issue_id, text, external_reference, event_ts


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
                return {'message': 'Invalid GitHub issue'}

            i_id, i_text, i_external_reference, event_ts = extract_data(issue)
            project = data.get('repository', {}).get('name')
            embeddings = await generate_github_content_embedding(openai_client, i_text)
            async with db.acquire() as conn:
                await create_github_content(
                    conn, project, 'issue', i_id, i_external_reference, i_text, event_ts, embeddings
                )
        else:
            logfire.debug('Action not supported: {data}', data=data)
            return {'message': 'Action not supported'}
    elif event_type == 'issue_comment':
        logfire.info('Received GitHub comment event: {data}', data=data)
        if data.get('action') == 'created':
            issue = data.get('issue')
            comment = data.get('comment')
            if not issue or not comment:
                logfire.error('Invalid GitHub issue comment: {data}', data=data)
                return {'message': 'Invalid GitHub issue comment'}

            if 'pull_request' in issue:  # Ignore pull requests comments
                logfire.error('Ignoring comment on GitHub pull request: {data}', data=data)
                return {'message': 'Ignoring comment on GitHub pull request'}

            # Comment has to be added to the issue text
            project = data.get('repository', {}).get('name')
            i_id, _, i_external_reference, _ = extract_data(issue)
            async with db.acquire() as conn:
                saved_issue = await get_github_content(conn, project, 'issue', i_id)
                if not saved_issue:
                    logfire.error(
                        'GitHub issue not found: {external_reference}', external_reference=i_external_reference
                    )
                    return {'message': 'GitHub issue not found'}

                _, c_text, _, _ = extract_data(comment)
                text = f'{saved_issue["text"]}\n\n{c_text}'
                embeddings = await generate_github_content_embedding(openai_client, text)
                await update_github_content(conn, project, 'issue', i_id, text, embeddings)
            logfire.info('Updated GitHub issue: {external_reference}', external_reference=i_external_reference)
        else:
            logfire.debug('Action not supported: {data}', data=data)
            return {'message': 'Action not supported'}

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
        if (channel := event.get('channel')) not in settings.slack_channel_ids:
            logfire.error('Invalid Slack channel: {channel}', channel=channel)
            return {'message': 'Invalid Slack channel'}

        if event.get('type') == 'message' and event.get('subtype') is None:
            author = event.get('user')
            text = event.get('text')
            message_id = event.get('client_msg_id')
            ts = datetime.fromtimestamp(float(event.get('ts')), tz=UTC)
            event_ts = event.get('event_ts')
            parent_event_ts = event.get('thread_ts')
            if not author or not text or not message_id or not event_ts:
                logfire.error('Invalid Slack message: {event}', event=event)
                return {'message': 'Invalid Slack message'}

            embedding = await generate_embedding(openai_client, text)

            async with db.acquire_trans() as conn:
                await create_slack_message(
                    conn,
                    channel=channel,
                    author=author,
                    message_id=message_id,
                    event_ts=event_ts,
                    parent_event_ts=parent_event_ts,
                    text=text,
                    ts=ts,
                    embedding=embedding,
                )

            logfire.info('Saved Slack message: {message_id}', message_id=message_id)

    return {'message': 'Event received'}
