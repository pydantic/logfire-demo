import asyncio
import json
import random
from typing import Any

import logfire
from httpx import AsyncClient, Response

requests_counter = logfire.metric_counter(
    'requests',
    unit='1',
    description='Number of requests made to the demo site',
)


async def get_homepage(client: AsyncClient):
    with logfire.span('get_homepage'):
        await _request(client, '')
        await _request(client, '/api/')
        await _request(client, '/map.jpg')


async def get_cities(client: AsyncClient, country: str | None = None):
    with logfire.span('get_cities'):
        params = {'country': country} if country else {}
        r = await _request(client, '/api/table', params=params)
        cities = r.json()[2]['components'][3]['data']
        assert isinstance(cities, list)

        await asyncio.sleep(random.random() * 8)
        if country or random.random() > 0.5:
            with logfire.span('get city'):
                city = random.choice(cities)
                await _request(client, f'/api/table/{city["id"]}')
        else:
            await search_cities(client)


async def search_cities(client: AsyncClient):
    with logfire.span('search_cities'):
        searches = 'united', 'mexi', 'ind', 'chin', 'jap', 'braz', 'nig'
        search = random.choice(searches)
        r = await _request(client, '/api/table/search', params={'q': search})

        options = r.json()['options']
        assert isinstance(options, list)
        option = random.choice(options)
        country = random.choice(option['options'])['value']
        await asyncio.sleep(random.random() * 4)
        await get_cities(client, country=country)


async def llm_query(client: AsyncClient):
    prompts = (
        'Tell me a joke',
        'Write me a recursive function to find a value in JSON for a particular key, in Python',
        'Write me a recursive function to find a value in JSON for a particular key, in Rust',
        'Write me a recursive function to find a value in JSON for a particular key, in JavaScript',
        'Write me a recursive function to find a value in JSON for a particular key, in TypeScript',
        'Write me an example recursive Postgres query',
    )
    prompt = random.choice(prompts)
    follow_ups = (
        'another please',
        'Can you give more context',
        'Can you explain why this is funny',
        'Please convert that to another language',
    )
    with logfire.span('llm_query'):
        r = await _request(client, '/api/llm')
        submit_url = _find_key(r.json(), 'submitUrl')
        for i in range(3):
            await asyncio.sleep(random.random() * 8)
            with logfire.span('llm_query {prompt=!r}', prompt=prompt, iteration=i) as span:
                r = await _request(client, submit_url, method='POST', data={'prompt': prompt})
                sse_endpoint = r.json()[1]['path']
                response = await stream_sse(client, sse_endpoint)
                span.set_attribute('response', response)
                if random.random() > 0.8:
                    break

                submit_url = _find_key(r.json(), 'submitUrl')
                prompt = random.choice(follow_ups)


async def stream_sse(client: AsyncClient, sse_endpoint: str) -> str | None:
    url = f'{SITE}/api{sse_endpoint}'
    lines = []
    with logfire.span('GET {url!r} stream', url=url) as span:
        requests_counter.add(1)
        async with client.stream('GET', url) as r:
            span.set_attribute('http_status_code', r.status_code)
            r.raise_for_status()
            span.set_attribute('headers', dict(r.headers))
            async for line in r.aiter_lines():
                lines.append(line)
            span.set_attribute('response_size', sum(len(line) for line in lines))
            span.set_attribute('chunks', len(lines))
    # last non-empty line
    last_line = next(filter(None, reversed(lines)), None)
    if last_line:
        return json.loads(last_line[6:])[0]['text']


SITE = 'https://demo.logfire.dev'


async def _request(
    client: AsyncClient, path: str, *, params: dict[str, str] | None = None, method: str = 'GET', **kwargs
) -> Response:
    with logfire.span('{method} {path!r} {params=}', method=method, path=path, params=params) as span:
        requests_counter.add(1)
        r = await client.request(method, f'{SITE}{path}', params=params, **kwargs)
        span.set_attribute('http_status_code', r.status_code)
        span.set_attribute('headers', r.headers)
        span.set_attribute('response_size', len(r.content))
        r.raise_for_status()
        if r.headers.get('content-type') == 'application/json':
            try:
                span.set_attribute('json_response', r.json())
            except ValueError:
                pass

    return r


def _find_key(json_data: Any, target_key):
    if isinstance(json_data, dict):
        for key, value in json_data.items():
            if key == target_key:
                return value
            if isinstance(value, dict | list):
                if found := _find_key(value, target_key):
                    return found
    elif isinstance(json_data, list):
        for item in json_data:
            if isinstance(item, dict | list):
                if found := _find_key(item, target_key):
                    return found
