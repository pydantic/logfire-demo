import importlib
import os
import sys

import logfire

service = sys.argv[1] if len(sys.argv) == 2 else os.getenv('SERVICE')
services = 'webui', 'tiling', 'worker'
# min duration is 100ms
logfire.install_auto_tracing(modules=[f'src.{s}' for s in services], min_duration=0.1)
if service is None:
    print('service argument variable not provided', file=sys.stderr)
    print('Available services:', ', '.join(services), file=sys.stderr)
elif service in services:

    def scrubbing_callback(match: logfire.ScrubMatch):
        if (
            match.path
            in [
                ['message', 'gh_data'],
                ['message', 'prompt'],
                ['attributes', 'prompt'],
                ['attributes', 'result', 'reason'],
            ]
            or match.path[:2]
            in [
                ['attributes', 'all_messages'],
                ['attributes', 'gh_data'],
            ]
            or match.path[:3]
            in [
                ['attributes', 'response', 'parts'],
            ]
        ):
            return match.value

    logfire.configure(
        service_name=service,
        code_source=logfire.CodeSource(
            repository='https://github.com/pydantic/logfire-demo',
            revision='main',
        ),
        scrubbing=logfire.ScrubbingOptions(callback=scrubbing_callback),
    )
    logfire.instrument_system_metrics()
    logfire.instrument_asyncpg()
    logfire.instrument_openai()

    module = importlib.import_module(f'.{service}', package='src')
    module.run()
else:
    print(f'Unknown service: {service}', file=sys.stderr)
    print('Available services:', ', '.join(services), file=sys.stderr)
