"""Approved DHEA/Pregnenolone SR masters: three blends, four terms, monthly supplies."""
import argparse
import json
from pathlib import Path
from import_additional_masters import prepare as prepare_batch, install as install_batch

RUN_ID = 'owner-approved-dhea-preg-sr-masters-20261026-v1'


def load_catalog():
    data = json.loads(Path(__file__).with_name('dhea_preg_catalog.json').read_text())
    expected = {f'DHEA-PREG-SRCAP-{a}-{b}MG-{m}M' for a,b in ((25,25),(25,50),(50,100)) for m in (1,3,6,12)}
    if len(data['products']) != 12 or {p['sku'] for p in data['products']} != expected:
        raise ValueError('Expected all 12 exact DHEA/Pregnenolone combinations')
    for p in data['products']:
        m=p['duration_months']
        if (p['therapy_id'] != 'hrt' or p['sku'] != f"DHEA-PREG-SRCAP-{p['dhea_mg']}-{p['pregnenolone_mg']}MG-{m}M"
                or p['supply_days_per_shipment'] != 30 or p['shipments_per_term'] != m
                or p['included_refills'] != m-1 or p['check_in_required'] is not False
                or p['capsules_per_shipment'] != 30 or p['total_capsules'] != 30*m):
            raise ValueError('Monthly supply contract differs from source: '+p['sku'])
    return data


def prepare(existing):
    return prepare_batch(existing,load_catalog())


def install(path,apply=False):
    return install_batch(path,apply,catalog=load_catalog(),run_id=RUN_ID)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    print(json.dumps(install(args.database,args.apply)))
