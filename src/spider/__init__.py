import asyncio
import random

import logfire
from httpx import AsyncClient

from . import tasks

logfire.configure(service_name='spider')
logfire.instrument_system_metrics()


def run():
    asyncio.run(arun())


async def arun():
    try:
        async with AsyncClient() as client:
            while True:
                match random.choice(('get_homepage', 'get_cities', 'llm_query')):
                    case 'get_homepage':
                        await tasks.get_homepage(client)
                    case 'get_cities':
                        await tasks.get_cities(client)
                    case 'llm_query':
                        await tasks.llm_query(client)

                delay = int(15 + random.random() * 45)
                with logfire.span(f'waiting {delay}s', delay=delay):
                    await asyncio.sleep(delay)
    except asyncio.CancelledError:
        logfire.info('Cancelled')
