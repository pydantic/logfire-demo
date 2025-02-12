from typing import Any

import asyncpg
import logfire
from httpx import AsyncClient
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models import ModelSettings

from ..common.db.github import GithubContentProject, fetch_issues_for_similarity_check, find_similar_issues


class SimilarityResult(BaseModel):
    percentage: int = Field(description='Similarity of the issues', ge=0, le=100)
    reason: str = Field(description='Reason for the similarity')


similar_issue_agent = Agent(
    'openai:gpt-4o',
    result_type=SimilarityResult,
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
