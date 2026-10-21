"""Build through the supplied cloud proxy, without retaining its trust bundle."""
import os
from pathlib import Path
import socket
import subprocess
from urllib.parse import urlsplit

environment = os.environ.copy()
config = Path('/workspace/scratch/docker-config')
config.mkdir(parents=True, exist_ok=True)
environment['DOCKER_CONFIG'] = str(config)
args = ['docker', 'build', '-t', 'wlmd-stripe-checkout:fly-test']
for name in ['HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY']:
    if environment.get(name):
        # Docker's predefined proxy arguments are omitted from image metadata.
        args += ['--build-arg', name]
proxy = environment.get('HTTPS_PROXY') or environment.get('HTTP_PROXY')
if proxy:
    host = urlsplit(proxy).hostname
    address = socket.getaddrinfo(host, None, socket.AF_INET)[0][4][0]
    args += ['--add-host', host + ':' + address]
bundle = environment.get('SSL_CERT_FILE')
if bundle:
    args += ['--secret', 'id=build_ca_bundle,src=' + bundle]
args += ['.']
raise SystemExit(subprocess.call(args, cwd=Path(__file__).resolve().parent, env=environment))
