import os
import importlib

import logfire


service = os.getenv('SERVICE')
services = 'webui', 'tiling', 'worker', 'spider'
# min duration is 1ms, spider isn't helped by auto tracing
logfire.install_auto_tracing(modules=[f'src.{s}' for s in services if s != 'spider'], min_duration=0.001)
if service is None:
    print('SERVICE environment variable not set')
    print('Available services:', ', '.join(services))
elif service in services:
    module = importlib.import_module(f'.{service}', package='src')
    module.run()
else:
    print(f'Unknown service: {service}')
