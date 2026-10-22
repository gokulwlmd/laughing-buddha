"""Loopback development with persistent synthetic state and no payment/network writes."""
import argparse
from pathlib import Path
import uvicorn
from app import Settings, create_app

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8081)
    args=parser.parse_args()
    origin=f'http://localhost:{args.port}'
    settings=Settings(public_url=origin,state_dir=Path(__file__).parent/'.state/development',synthetic=True)
    app=create_app(settings)
    print(f'Demo admin: {origin}/admin',flush=True)
    if not app.state.admin.owner():
        print(f'Private local owner setup: {origin}/admin?setup={app.state.admin.setup_token}',flush=True)
    print('Synthetic catalog only. Payment authorization and capture are blocked.',flush=True)
    uvicorn.run(app,host='127.0.0.1',port=args.port,workers=1,access_log=False,proxy_headers=False)
