import os

service = os.getenv('SERVICE')
match service:
    case 'webui':
        from . import webui

        webui.run()
    case 'tiling':
        from . import tiling

        tiling.run()
    case 'worker':
        from . import worker

        worker.run()
    case _:
        raise RuntimeError(f'Unknown service: {service}')
