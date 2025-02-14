import asyncio
import logging.config
import time

import asyncpg
import logfire
from arq import cron
from arq.connections import RedisSettings
from arq.worker import run_worker
from httpx import AsyncClient
from openai import AsyncOpenAI
from pydantic_ai import Agent

from .docs_embeddings import update_docs_embeddings
from .github_similar_content import similar_issue_agent, suggest_similar_issues
from .settings import settings

logfire.configure(service_name='worker')
logfire.instrument_system_metrics()
logfire.instrument_asyncpg()
logfire.instrument_openai()


async def startup(ctx):
    openai_http_client = AsyncClient()
    openai_client = openai_client = AsyncOpenAI(http_client=openai_http_client)

    ai_agent = Agent(
        'openai:gpt-4o',
        result_type=str,
        system_prompt='Be concise, reply with maximum 50 tokens.',
    )

    client = AsyncClient()

    ctx.update(
        client=client,
        pg_pool=await asyncpg.create_pool(settings.pg_dsn),
        openai_client=openai_client,
        ai_agent=ai_agent,
        similar_issue_agent=similar_issue_agent,
    )


async def shutdown(ctx):
    await ctx['client'].aclose()
    await ctx['openai_client'].close()
    await asyncio.wait_for(ctx['pg_pool'].close(), timeout=2.0)


async def pydantic_doc_embeddings(ctx) -> None:
    """Update the embeddings for the pydantic documentation."""
    with logfire.span('update pydantic ai docs embeddings'):
        await update_docs_embeddings(
            ctx['client'],
            ctx['pg_pool'],
            ctx['openai_client'],
            'https://docs.pydantic.dev/dev/llms.txt',
            'pydantic_docs',
        )


async def pydantic_ai_doc_embeddings(ctx) -> None:
    """Update the embeddings for the pydantic ai documentation."""
    with logfire.span('update pydantic ai docs embeddings'):
        await update_docs_embeddings(
            ctx['client'], ctx['pg_pool'], ctx['openai_client'], 'https://ai.pydantic.dev/llms.txt', 'pydantic_ai_docs'
        )


async def logfire_doc_embeddings(ctx) -> None:
    """Update the embeddings for the logfire documentation."""
    with logfire.span('update logfire docs embeddings'):
        await update_docs_embeddings(
            ctx['client'],
            ctx['pg_pool'],
            ctx['openai_client'],
            'https://logfire.pydantic.dev/docs/llms.txt',
            'logfire_docs',
        )


QUESTIONS = [
    'What is Pydantic?',
    'What is PydanticAI?',
    'What is Pydantic Logfire?',
    'What are the main features of PydanticAI?',
    'What are the main features of Pydantic Logfire?',
    'Where is the documentation for the Pydantic Logfire schema?',
    'What database does Pydantic Logfire use?',
    'Where can I find the Pydantic public slack contact details?',
    "What's the url for the Pydantic Logfire docs?",
    'How do I invite my team members to Logfire?',
]


async def llm_query(ctx) -> None:
    """Query the LLM model with some questions."""
    with logfire.span('query llm'):
        question_index = int(time.time() // (5 * 60)) % len(QUESTIONS)  # Divide time into 5-minute intervals
        question = QUESTIONS[question_index]
        response = await ctx['ai_agent'].run(question)
        logfire.info('Question: {question} Answer: {response}', question=question, response=response.data)


async def check_new_created_issues(ctx) -> None:
    """Suggest similar issues for new issues and post them as comments."""
    with logfire.span('check new issues for similarity'):
        await suggest_similar_issues(
            ctx['pg_pool'],
            ctx['similar_issue_agent'],
            ctx['client'],
            settings.vector_distance_threshold,
            settings.ai_similarity_threshold,
        )


class WorkerSettings:
    functions = [
        pydantic_doc_embeddings,
        pydantic_ai_doc_embeddings,
        logfire_doc_embeddings,
        llm_query,
        check_new_created_issues,
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_dsn)
    cron_jobs = [
        cron(pydantic_ai_doc_embeddings, hour={10, 22}, minute=0),
        cron(logfire_doc_embeddings, hour={1, 13}, minute=0),
        cron(pydantic_doc_embeddings, hour={2, 14}, minute=0),
        cron(llm_query, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
        cron(check_new_created_issues, minute={0, 10, 20, 30, 40, 50}),
    ]


def run():
    logging.config.dictConfig(
        {
            'version': 1,
            'disable_existing_loggers': False,
            'handlers': {
                'logfire': {'level': 'INFO', 'class': 'logfire.integrations.logging.LogfireLoggingHandler'},
            },
            'loggers': {'arq': {'handlers': ['logfire'], 'level': 'INFO'}},
        }
    )

    run_worker(WorkerSettings)  # type: ignore
