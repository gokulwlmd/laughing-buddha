"""Run the isolated sample patient portal on loopback; no payment integrations."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from patient_demo.app import create_app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8873)
    parser.add_argument('--state-dir', type=Path, default=Path(__file__).resolve().parents[1] / '.state' / 'patient-demo')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Use an unprivileged port')
    origin = f'http://127.0.0.1:{args.port}'
    print(json.dumps({'frontend': origin, 'api': origin, 'swagger': origin + '/sites/willow-health/docs',
                      'mode': 'patient-demo', 'payments_enabled': False}), flush=True)
    uvicorn.run(create_app(args.state_dir), host='127.0.0.1', port=args.port,
                log_level='warning', access_log=False, proxy_headers=False)
