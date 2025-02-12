from typing import Any

import asyncpg
import logfire
from httpx import AsyncClient
from pydantic import BaseModel, Field
from pydantic_ai import Agent

from ..common.db.github import GithubContentProject, fetch_issues_for_similarity_check, find_similar_issues


class SimilarityResult(BaseModel):
    percentage: int = Field(description='Similarity of the issues', ge=0, le=100)


similar_issue_agent = Agent(
    'openai:gpt-4o',
    result_type=SimilarityResult,
    system_prompt=(
        'I have two GitHub issues, and I want you to analyze their similarity.'
        'Please provide a similarity score as a percentage (0% = completely different, 100% = identical).'
        'Analyze their content, intent, and meaning. Provide a **single similarity percentage**'
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


async def _post_github_comment(
    github_client: AsyncClient, project: GithubContentProject, issue_link: str, similar_issues: list[dict[str, Any]]
) -> None:
    # Find the issue number from the issue link
    issue_number = issue_link.split('/')[-1]
    url = f'https://api.github.com/repos/pydantic/{project}/issues/{issue_number}/comments'

    # Generate the comment body
    issue_links = '\n'.join(
        [
            f'{i + 1}. "{similar_issue["link"]}" ({similar_issue["percentage"]}% similar)'
            for i, similar_issue in enumerate(similar_issues)
        ]
    )
    body = f'PydanticAI Github Bot Found 3 issues similar to this one: \n{issue_links}'

    response = await github_client.post(
        url,
        json={'body': body},
    )
    response.raise_for_status()


async def suggest_similar_issues(pg_pool: asyncpg.Pool, similar_issue_agent: Agent, github_client: AsyncClient) -> None:
    async with pg_pool.acquire() as conn:
        # Fetch new created issues for similarity check
        issues = await fetch_issues_for_similarity_check(conn)
        if not issues:
            logfire.info('No new created issues found')
            return
        logfire.info(f'Found {len(issues)} new created issues')

        for issue in issues:
            issue_link = issue['external_reference']
            with logfire.span(f'Checking issue {issue_link}'):
                # Fetch similar issues by vector similarity
                similar_issues = await find_similar_issues(conn, issue['id'], issue['project'])
                logfire.info(f'Found {len(similar_issues)} similar issues for issue {issue_link}')

                final_similar_issues: list[dict[str, Any]] = []
                for similar_issue in similar_issues:
                    similar_issue_link = similar_issue['external_reference']
                    # Skip similar issues with distance less than 90
                    # It could be done in database level, but we did it here to see some
                    # similar issues in logs. This help us to adjust the threshold
                    if similar_issue['distance'] < 0.9:
                        logfire.info(
                            f'Skipping similar issue {similar_issue_link} due to distance {similar_issue["distance"]}'
                        )

                    # Get similarity percentage from the AI agent
                    logfire.info(
                        f'Checking similarity between issue {issue_link} and similar issue {similar_issue_link}'
                    )
                    similarity_result = await similar_issue_agent.run(
                        _generate_query(issue['text'], similar_issue['text'])
                    )
                    if similarity_result.data.percentage > 90:
                        final_similar_issues.append(
                            {'link': similar_issue_link, 'percentage': similarity_result.data.percentage}
                        )

                if not final_similar_issues:
                    logfire.info(f'No similar issues found for {issue_link}')
                    continue

                await _post_github_comment(github_client, issue['project'], issue_link, final_similar_issues)
