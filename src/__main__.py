import os
import importlib

service = os.getenv('SERVICE')
services = 'webui', 'tiling', 'worker', 'spider'
if service is None:
    print('SERVICE environment variable not set')
    print('Available services:', ', '.join(services))
elif service in services:
    module = importlib.import_module(f'.{service}', package='src')
    module.run()
else:
    print(f'Unknown service: {service}')
