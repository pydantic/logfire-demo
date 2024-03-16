import os

service = os.getenv('SERVICE')
if service == 'webui':
    from .webui import run

    run()
elif service == 'tiling':
    from .tiling import run

    run()
else:
    raise RuntimeError(f'Unknown service: {service}')
