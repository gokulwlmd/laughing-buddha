"""Prepare this API's separate volume, then drop root before serving."""
import os
from pathlib import Path
import sys

state=Path('/data');state.mkdir(mode=0o700,exist_ok=True)
os.chown(state,10001,10001);os.chmod(state,0o700)
os.setgroups([]);os.setgid(10001);os.setuid(10001)
os.execv(sys.executable,[sys.executable,'-m','uvicorn','demo.public:create_public_app','--factory',
    '--host','0.0.0.0','--port','8080','--workers','1','--no-access-log','--no-proxy-headers'])
