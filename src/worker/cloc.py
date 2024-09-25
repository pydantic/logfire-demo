import asyncio
import base64
from collections import defaultdict
from contextlib import suppress
from typing import Literal, TypedDict

import logfire
from httpx import AsyncClient, HTTPStatusError


async def cloc_recursive(client: AsyncClient, repo: str) -> dict[str, int]:
    file_types = defaultdict(int)

    async def get_file(url: str, file_type: str, file_name: str) -> None:
        with logfire.span('processing file {file_name=}', file_name=file_name):
            r = await client.get(url)
            r.raise_for_status()
            content = r.json()['content']
            loc = base64.b64decode(content.encode().replace(b'\n', b'')).count(b'\n')
            file_types[file_type] += loc

    async def get_dir(url: str, file_name: str) -> None:
        with logfire.span('processing dir {file_name=}', file_name=file_name):
            r = await client.get(url)
            r.raise_for_status()
            tasks = []

            for p in r.json():
                name = p['name']
                match p['type']:
                    case 'file':
                        if '.' in p['name']:
                            if file_type := file_type_lookup.get(p['name'].rsplit('.', 1)[1]):
                                tasks.append(get_file(p['url'], file_type, name))
                    case 'dir':
                        tasks.append(get_dir(p['url'], name))

            await asyncio.gather(*tasks)

    try:
        await get_dir(f'https://api.github.com/repos/{repo}/contents/', 'root')
    except HTTPStatusError as exc:
        resp = exc.response
        try:
            data = resp.json()
        except ValueError:
            data = resp.text
        logfire.error(
            'cloc_recursive unexpected response {status}',
            status=resp.status_code,
            response_data=data,
            response_headers=resp.headers,
        )
        raise
    else:
        return dict(file_types)


async def cloc_queue(client: AsyncClient, repo: str) -> dict[str, int]:
    """
    Fast but hard to debug.
    """
    file_types = defaultdict(int)

    async def worker(queue: asyncio.Queue[GitHubFile | GitHubDir]) -> None:
        try:
            while True:
                task = await queue.get()
                try:
                    task_type = task['type']
                    task_url = task['url']
                    with logfire.span(
                        'processing {task_type} {path=} {qsize=}',
                        task_type=task_type,
                        path=task_url.split('/', 3)[3],
                        qsize=queue.qsize(),
                    ):
                        r = await client.get(task_url)
                        r.raise_for_status()
                        data = r.json()

                        if task_type == 'file':
                            content = data['content']
                            loc = base64.b64decode(content.encode().replace(b'\n', b'')).count(b'\n')
                            file_types[task['file_type']] += loc
                        else:
                            for p in data:
                                match p['type']:
                                    case 'file':
                                        if '.' in p['name']:
                                            if file_type := file_type_lookup.get(p['name'].rsplit('.', 1)[1]):
                                                f = GitHubFile(type='file', url=p['url'], file_type=file_type)
                                                await queue.put(f)
                                    case 'dir':
                                        await queue.put(GitHubDir(type='dir', url=p['url']))
                finally:
                    queue.task_done()
        except HTTPStatusError as exc:
            try:
                data = exc.response.json()
            except ValueError:
                data = exc.response.text
            logfire.error('worker failed: {exc!r}', exc=exc, response_data=data, response_headers=exc.response.headers)
            raise
        except Exception as exc:
            logfire.error('worker failed: {exc!r}', exc=exc)
            raise

    queue_ = asyncio.Queue()
    tasks = [asyncio.create_task(worker(queue_)) for _ in range(50)]

    await queue_.put(GitHubDir(type='dir', url=f'https://api.github.com/repos/{repo}/contents/'))

    # wait for the queue to be empty, periodically check if any tasks have failed
    while True:
        try:
            await asyncio.wait_for(queue_.join(), timeout=0.5)
        except TimeoutError:
            try:
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=0.5)
            except TimeoutError:
                pass
        else:
            break

    [t.cancel() for t in tasks]
    with suppress(asyncio.CancelledError):
        await asyncio.gather(*tasks)

    return dict(file_types)


class GitHubFile(TypedDict):
    type: Literal['file']
    url: str
    file_type: str


class GitHubDir(TypedDict):
    type: Literal['dir']
    url: str


file_type_lookup: dict[str, str] = {
    'py': 'Python',
    'js': 'JavaScript',
    'jsx': 'JavaScript',
    'ts': 'TypeScript',
    'tsx': 'TypeScript',
    'java': 'Java',
    'c': 'c',
    'h': 'c',
    'cpp': 'C++',
    'cs': 'C#',
    'php': 'PHP',
    'html': 'HTML',
    'css': 'CSS',
    'scss': 'CSS',
    'sass': 'CSS',
    'rb': 'Ruby',
    'r': 'R',
    'go': 'Go',
    'rs': 'Rust',
    'swift': 'Swift',
    'kt': 'Kotlin',
    'scala': 'Scala',
    'lua': 'Lua',
    'pl': 'Perl',
    'sh': 'Shell',
    'm': 'Objective-c',
    'md': 'Markdown',
    'rst': 'Rst',
    'yaml': 'YAML',
    'yml': 'YAML',
    'toml': 'TOML',
    'json': 'JSON',
}
