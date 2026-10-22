"""Fail closed if the manual staging workflow targets live state or enables payments."""
import argparse
import json
from pathlib import Path
import tomllib
from urllib.request import urlopen

parser=argparse.ArgumentParser();parser.add_argument('--health',action='store_true');args=parser.parse_args()
root=Path(__file__).resolve().parents[1]/'tools/stripe-v2-checkout'
staging=tomllib.loads((root/'fly.staging.toml').read_text())
live=tomllib.loads((root/'fly.toml').read_text())
assert staging['app']=='wlmd-checkout-staging-0f89b1bb'
assert staging['app']!=live['app']
assert staging['env']['CHECKOUT_ENVIRONMENT']=='staging'
assert staging['env']['CHECKOUT_AUTHORIZATION_VERIFIED']=='0'
assert staging['env']['CHECKOUT_PUBLIC_URL']==f"https://{staging['app']}.fly.dev"
assert staging['env']['CHECKOUT_STATE_DIR']=='/data'
assert staging['mounts']==[{'source':'staging_data','destination':'/data'}]
assert not set(m['source'] for m in staging['mounts']).intersection(m['source'] for m in live['mounts'])
if args.health:
    with urlopen(staging['env']['CHECKOUT_PUBLIC_URL']+'/health',timeout=60) as response:
        health=json.load(response)
    assert health['synthetic'] is True and health['payments_blocked'] is True
    assert health['authorization_contract_verified'] is False
print('Staging isolation verified'+('; hosted synthetic mode and payment block verified.' if args.health else '.'))
