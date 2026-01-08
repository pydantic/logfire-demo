import time
from typing import Any

import asyncpg
import jwt
import logfire
from httpx import AsyncClient
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models import ModelSettings

from ..common.db.github import (
    GithubContentProject,
    fetch_issues_for_similarity_check,
    find_similar_issues,
    update_similar_issues,
)
from .settings import settings


class SimilarityResult(BaseModel):
    percentage: int = Field(description='Similarity of the issues', ge=0, le=100)
    reason: str = Field(description='Reason for the similarity')


similar_issue_agent = Agent(
    'gateway/openai:gpt-5',
    output_type=SimilarityResult,
    model_settings=ModelSettings(temprature=0.1),
    system_prompt=(
        """
Your task is to provide a detailed similarity analysis while maintaining strict output format requirements.

ANALYSIS CRITERIA:
1. Semantic Similarity (40% weight)
   - Core problem or feature request
   - Technical domain and scope
   - Expected behavior and outcomes

2. Implementation Details (30% weight)
   - Technical approach suggested
   - Dependencies mentioned
   - Code snippets or examples

3. Context & Requirements (30% weight)
   - Project context and constraints
   - User impact and priorities
   - Environment and version details

SIMILARITY SCALE:
0-20%: Fundamentally different issues
21-40%: Slight overlaps but largely distinct
41-60%: Moderate similarity in some aspects
61-80%: Significant overlap in core aspects
81-100%: Nearly identical issues

RULES:
- Ignore superficial similarities (writing style, formatting)
- Consider partial matches in technical requirements
- Account for implicit similarities in problem domain
- Look for shared root causes in bug reports
- Consider related feature requests as partial matches

OUTPUT FORMAT:
1. Provide a single integer similarity score (0-100)
2. The score must be divisible by 5 (e.g., 75 not 77)
3. No explanation unless explicitly requested

EXAMPLE PAIRS AND SCORES:

# High Similarity (80-100%)
Issue 1: "Error: Connection timeout when processing large files >500MB"
Issue 2: "Timeout occurred during batch processing of files >1GB"
Score: 85
Reason: Nearly identical core issue (timeout during large file processing), same technical domain, similar scope

Issue 1: "Add dark mode support to dashboard UI"
Issue 2: "Implement dark theme for main dashboard"
Score: 90
Reason: Same feature request, same component, identical scope

# Moderate Similarity (40-79%)
Issue 1: "Redis connection fails with timeout after 30 seconds"
Issue 2: "MongoDB connection timeout in high-load scenarios"
Score: 60
Reason: Similar problem (database timeout) but different databases and contexts

Issue 1: "Add user authentication via Google OAuth"
Issue 2: "Implement SSO support for Google accounts"
Score: 75
Reason: Related authentication features with overlapping implementation

# Low Similarity (0-39%)
Issue 1: "Browser crashes when uploading large files"
Issue 2: "Timeout during large file upload"
Score: 35
Reason: Different core issues (crash vs timeout) despite similar trigger

Issue 1: "Add PDF export functionality"
Issue 2: "Fix PDF rendering bug in preview"
Score: 25
Reason: Same component (PDF) but different types of issues (feature vs bug)

# Zero Similarity
Issue 1: "Update documentation for API endpoints"
Issue 2: "Fix memory leak in image processing"
Score: 0
Reason: Completely different domains, types, and purposes
"""
    ),
)


def _generate_query(issue_1_text: str, issue_2_text: str) -> str:
    return f"""
    Are these two GitHub issues similar?
    **Issue 1:**
    "{issue_1_text}"

    **Issue 2:**
    "{issue_2_text}"
    """


async def _generate_github_app_access_token(
    client: AsyncClient, app_id: int, installation_id: int, private_key: str
) -> str:
    """Generate a GitHub App access token."""
    # Generate a GitHub App JWT
    now = int(time.time())
    payload = {'iat': now, 'exp': now + 600, 'iss': app_id}
    jwt_token = jwt.encode(payload, private_key, algorithm='RS256')

    # Get Installation Access Token
    url = f'https://api.github.com/app/installations/{installation_id}/access_tokens'
    headers = {'Authorization': f'Bearer {jwt_token}', 'Accept': 'application/vnd.github.v3+json'}
    response = await client.post(url, headers=headers)
    return response.json().get('token')


async def _post_github_comment(
    client: AsyncClient,
    access_token: str,
    project: GithubContentProject,
    issue_link: str,
    similar_issues: list[dict[str, Any]],
) -> None:
    # Find the issue number from the issue link
    issue_number = issue_link.split('/')[-1]
    url = f'https://api.github.com/repos/pydantic/{project}/issues/{issue_number}/comments'

    # Generate the comment body
    issue_links = '\n'.join(
        [
            f'{i + 1}. "{similar_issue["link"]}" ({similar_issue["ai_similarity"]}% similar)'
            for i, similar_issue in enumerate(similar_issues)
        ]
    )
    body = f'PydanticAI Github Bot Found {len(similar_issues)} issues similar to this one: \n{issue_links}'

    response = await client.post(
        url,
        json={'body': body},
        headers={'Authorization': f'Bearer {access_token}', 'Accept': 'application/vnd.github.v3+json'},
    )
    response.raise_for_status()


async def suggest_similar_issues(
    pg_pool: asyncpg.Pool,
    similar_issue_agent: Agent,
    client: AsyncClient,
    vector_distance_threshold: float,
    ai_similarity_threshold: int,
) -> None:
    github_access_token = None

    async with pg_pool.acquire() as conn:
        # Fetch new issues for similarity check
        issues = await fetch_issues_for_similarity_check(conn)
        if not issues:
            logfire.info('No new issues found')
            return
        logfire.info(f'Found {len(issues)} new issues')

        for issue in issues:
            issue_link = issue['external_reference']
            with logfire.span(f'Checking issue {issue_link}'):
                # Fetch similar issues by vector similarity
                similar_issues = await find_similar_issues(conn, issue['id'], issue['project'])
                logfire.info(f'Found {len(similar_issues)} similar issues for issue {issue_link}')

                similar_issues_obj: list[dict[str, Any]] = []
                for similar_issue in similar_issues:
                    similar_issue_link = similar_issue['external_reference']
                    distance = similar_issue['distance']
                    obj = {
                        'link': similar_issue_link,
                        'distance': distance,
                        'ai_similarity': None,
                        'post_comment': False,
                    }
                    # Skip similar issues with distance > vector_distance_threshold
                    # It could be done in database level, but we did it here to see some
                    # similar issues in logs. This help us to adjust the threshold
                    if distance <= vector_distance_threshold:
                        # Get similarity percentage from the AI agent
                        logfire.info(
                            f'Checking similarity between issue {issue_link} and similar issue {similar_issue_link}'
                        )
                        similarity_result = await similar_issue_agent.run(
                            _generate_query(issue['text'], similar_issue['text'])
                        )
                        obj['ai_similarity'] = similarity_result.output.percentage
                        if similarity_result.output.percentage > ai_similarity_threshold:
                            obj['post_comment'] = True
                    else:
                        logfire.info(f'Skipping similar issue {similar_issue_link} due to distance {distance}')

                    similar_issues_obj.append(obj)

                # Filter similar issues to post comments
                issues_to_comment = [issue for issue in similar_issues_obj if issue['post_comment']]
                if not issues_to_comment:
                    logfire.info(f'No similar issues found for {issue_link}')
                else:
                    # Github access token is valid for 10 minutes. We need to generate a new one
                    # if we don't have it. As the task runs every 10 minutes, we need to generate
                    # a new token every time the task runs.
                    if not github_access_token:
                        github_access_token = await _generate_github_app_access_token(
                            client,
                            settings.github_app_id,
                            settings.github_app_installation_id,
                            settings.github_app_private_key,
                        )
                    await _post_github_comment(
                        client, github_access_token, issue['project'], issue_link, issues_to_comment
                    )
                    logfire.info(f'Posted similar issues for {issue_link}')

                # Update the similar issues in the database
                await update_similar_issues(conn, issue['id'], similar_issues_obj)
