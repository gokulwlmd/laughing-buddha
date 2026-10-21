"""Push the tested image using OCI registry HTTPS requests through the supplied proxy."""
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import tarfile
import subprocess
import tomllib
from urllib import error, parse, request

ROOT = Path("/workspace/scratch/fly-image")
ROOT.mkdir(parents=True, exist_ok=True)
BUILD_DIR = Path(__file__).resolve().parent
ORIGIN = 'https://registry.fly.io'
REPOSITORY = tomllib.loads((BUILD_DIR / 'fly.toml').read_text())['app']
PREFIX = '/v2/' + REPOSITORY
MEDIA = 'application/vnd.docker.distribution.manifest.v2+json'


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError('Registry redirected outside the current request; inspect before continuing')


opener = request.build_opener(NoRedirect())
authorization = 'Basic ' + base64.b64encode(('x:' + os.environ['FLY_API_TOKEN']).encode()).decode()


def call(method, path, data=None, content_type=None, allow_missing=False):
    url = parse.urljoin(ORIGIN, path)
    parsed = parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.netloc != 'registry.fly.io':
        raise RuntimeError('Unexpected registry upload destination')
    headers = {'Authorization': authorization, 'Accept': MEDIA}
    if content_type:
        headers['Content-Type'] = content_type
    try:
        with opener.open(request.Request(url, data=data, method=method, headers=headers), timeout=120) as response:
            return response.status, response.headers, response.read()
    except error.HTTPError as exc:
        if allow_missing and exc.code == 404:
            return 404, exc.headers, b''
        raise RuntimeError(f'Registry {method} failed with HTTP {exc.code}') from None
    except (error.URLError, TimeoutError):
        raise RuntimeError(f'Registry {method} transport failed; reconcile uploaded digest before retrying') from None


def digest(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def upload(data, label):
    value = digest(data)
    status, _, _ = call('HEAD', PREFIX + '/blobs/' + value, allow_missing=True)
    if status == 200:
        print(json.dumps({'blob': label, 'status': 'already_present'}), flush=True)
        return value
    _, headers, _ = call('POST', PREFIX + '/blobs/uploads/', b'', 'application/octet-stream')
    location = headers.get('Location')
    if not location:
        raise RuntimeError('Registry omitted upload location')
    print(json.dumps({'blob': label, 'status': 'uploading', 'bytes': len(data)}), flush=True)
    # Use the registry's standard chunked protocol: large single requests lose
    # authentication in this environment's proxy, while small requests succeed.
    chunk_size = 512 * 1024
    for offset in range(0, len(data), chunk_size):
        chunk = data[offset:offset + chunk_size]
        status, headers, _ = call('PATCH', location, chunk, 'application/octet-stream')
        if status != 202:
            raise RuntimeError('Registry did not accept an upload chunk')
        location = headers.get('Location') or location
        if (offset // chunk_size) % 8 == 0:
            print(json.dumps({'blob': label, 'bytes_sent': offset + len(chunk)}), flush=True)
    target = location + ('&' if '?' in location else '?') + parse.urlencode({'digest': value})
    status, _, _ = call('PUT', target, b'', 'application/octet-stream')
    if status != 201:
        raise RuntimeError('Registry did not confirm blob upload')
    print(json.dumps({'blob': label, 'status': 'uploaded'}), flush=True)
    return value


docker_environment = os.environ.copy()
docker_environment['DOCKER_CONFIG'] = '/workspace/scratch/docker-config'
subprocess.run(['docker', 'image', 'save', 'wlmd-stripe-checkout:fly-test', '-o', str(ROOT / 'image.tar')], env=docker_environment, check=True)

with tarfile.open(ROOT / 'image.tar') as archive:
    metadata = json.load(archive.extractfile('manifest.json'))[0]
    config_data = archive.extractfile(metadata['Config']).read()
    config = json.loads(config_data)
    assert config['architecture'] == 'amd64' and config['os'] == 'linux'
    assert not any(item.split('=', 1)[0] in ['FLY_API_TOKEN', 'STICKY_API_USERNAME', 'STICKY_API_PASSWORD', 'HTTPS_PROXY'] for item in config['config'].get('Env', []))
    config_digest = upload(config_data, 'config')
    layers = []
    for number, (path, expected_diff) in enumerate(zip(metadata['Layers'], config['rootfs']['diff_ids'], strict=True), 1):
        raw = archive.extractfile(path).read()
        assert digest(raw) == expected_diff, 'Exported image layer does not match its configuration'
        compressed = gzip.compress(raw, compresslevel=6, mtime=0)
        value = upload(compressed, f'layer_{number}')
        layers.append({'mediaType': 'application/vnd.docker.image.rootfs.diff.tar.gzip', 'size': len(compressed), 'digest': value})
    manifest = {'schemaVersion': 2, 'mediaType': MEDIA,
        'config': {'mediaType': 'application/vnd.docker.container.image.v1+json', 'size': len(config_data), 'digest': config_digest},
        'layers': layers}
    manifest_data = json.dumps(manifest, separators=(',', ':')).encode()
    expected = digest(manifest_data)
    status, headers, _ = call('PUT', PREFIX + '/manifests/checkout-2usd', manifest_data, MEDIA)
    assert status == 201 and headers.get('Docker-Content-Digest') == expected
    status, _, returned = call('GET', PREFIX + '/manifests/' + expected)
    assert status == 200 and digest(returned) == expected
    result = {'repository': REPOSITORY, 'image': ORIGIN.removeprefix('https://') + '/' + REPOSITORY + '@' + expected,
        'manifest_verified': True, 'config_digest': config_digest, 'layer_count': len(layers)}
    (ROOT / 'push_result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)
