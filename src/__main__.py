import importlib
import os
import sys

import logfire

service = sys.argv[1] if len(sys.argv) == 2 else os.getenv('SERVICE')
services = 'webui', 'tiling', 'worker', 'spider'
# min duration is 1ms, spider isn't helped by auto tracing
logfire.install_auto_tracing(modules=[f'src.{s}' for s in services if s != 'spider'], min_duration=0.01)
if service is None:
    print('service argument variable not provided')
    print('Available services:', ', '.join(services))
elif service in services:
    module = importlib.import_module(f'.{service}', package='src')
    module.run()
else:
    print(f'Unknown service: {service}')
    print('Available services:', ', '.join(services))
