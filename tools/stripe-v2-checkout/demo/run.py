"""Run the separate sample frontend and two-call API on loopback only."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from demo.site_api import DemoSettings, create_demo_app, create_frontend_app


async def run(api_port,frontend_port):
    cfg = DemoSettings(api_origin=f'http://127.0.0.1:{api_port}',frontend_origin=f'http://127.0.0.1:{frontend_port}')
    options = {'host':'127.0.0.1','log_level':'warning','access_log':False,'proxy_headers':False}
    servers = [uvicorn.Server(uvicorn.Config(create_demo_app(cfg),port=api_port,**options)),
               uvicorn.Server(uvicorn.Config(create_frontend_app(cfg),port=frontend_port,**options))]
    tasks=[asyncio.create_task(server.serve()) for server in servers]
    try:
        while not all(server.started for server in servers):
            if any(task.done() for task in tasks):
                await asyncio.gather(*tasks)
                raise RuntimeError('Demo servers did not start')
            await asyncio.sleep(.01)
        print(json.dumps({'frontend':cfg.frontend_origin,'api':cfg.api_origin,'swagger':cfg.api_origin+'/sites/willow-health/docs','payments_enabled':False}),flush=True)
        await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
    finally:
        for server in servers:server.should_exit=True
        await asyncio.gather(*tasks,return_exceptions=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-port',type=int,default=8871)
    parser.add_argument('--frontend-port',type=int,default=8872)
    args=parser.parse_args()
    if not (1024 <= args.api_port <= 65535 and 1024 <= args.frontend_port <= 65535) or args.api_port == args.frontend_port:
        parser.error('Use two different unprivileged ports')
    asyncio.run(run(args.api_port,args.frontend_port))
