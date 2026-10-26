"""Add the approved ED combination tablets as one reusable master template."""
import argparse
import json
from pathlib import Path
from import_additional_masters import prepare as prepare_batch, install as install_batch

RUN_ID = 'owner-approved-ed-pt141-vardenafil-combinations-20261026-v1'
EXPECTED = {'TADA-OXYT-PT141-RDT-10MG-100IU-1MG':8, 'TADA-OXYT-PT141-RDT-20MG-100IU-2MG':8,
            'TADA-VARD-RDT-5MG-5MG':10}


def load_catalog():
    catalog = json.loads(Path(__file__).with_name('ed_advanced_catalog.json').read_text())
    products = catalog['products']
    expected = {f'{prefix}-{m}M' for prefix in EXPECTED for m in (1,3,6,12)}
    if len(products)!=12 or {p['sku'] for p in products}!=expected:
        raise ValueError('Expected exactly the 12 approved sheet combinations')
    for p in products:
        m=p['duration_months'];days=30 if m==1 else 90;count=m*30//days
        qty=EXPECTED[p['sku'].rsplit('-',1)[0]]
        if (p['therapy_id']!='erectile-dysfunction' or p['supply_days_per_shipment']!=days
                or p['shipments_per_term']!=count or p['included_refills']!=count-1
                or p['check_in_required'] is not False or p['tablets_per_month']!=qty
                or p['tablets_per_shipment']!=qty*days//30 or p['total_tablets']!=qty*m):
            raise ValueError('Source delivery/quantity contract mismatch: '+p['sku'])
    return catalog


def prepare(existing):
    return prepare_batch(existing,load_catalog())


def install(path,apply=False):
    return install_batch(path,apply,catalog=load_catalog(),run_id=RUN_ID)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    print(json.dumps(install(args.database,args.apply)))
