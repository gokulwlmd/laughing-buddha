"""Initialize the mounted state directory, then run the service without root."""
import os
from pathlib import Path
import sys

state = Path('/data')
state.mkdir(mode=0o700, exist_ok=True)
os.chown(state, 10001, 10001)
os.chmod(state, 0o700)
os.setgroups([])
os.setgid(10001)
os.setuid(10001)
os.execv(sys.executable, [sys.executable, '-m', 'uvicorn', 'app:app',
    '--host', '0.0.0.0', '--port', '8080', '--workers', '1',
    '--no-access-log', '--no-proxy-headers'])
