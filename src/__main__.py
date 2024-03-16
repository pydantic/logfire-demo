import sys

task = sys.argv[1]
if task == 'webui':
    from .webui import run

    run()
else:
    raise RuntimeError(f'Unknown task: {task}')
