"""Approved 30/90-day skin topicals, paired base/-SUB, with the Urea source discrepancy resolved by the owner."""
import argparse
import json
from pathlib import Path
from import_additional_masters import prepare as prepare_batch, install as install_batch

RUN_ID = 'owner-approved-skin-topicals-20261026-v1'
UREA_SKU = 'DERM-SLCYLC-ZOX-NIACIN-UREA-CREAM'
PREFIXES = ('DERM-EST-VC-HYA-TOPICAL', 'DERM-HYDROQ-KOJI-NIACIN-TOPICAL', 'DERM-TRET-NIACIN-VC-TOPICAL')


def load_catalog():
    data = json.loads(Path(__file__).with_name('skin_topical_catalog.json').read_text())
    expected = {p+s for p in PREFIXES for s in ('','-3M')} | {UREA_SKU, UREA_SKU+'-3M'}
    if len(data['products']) != 8 or {p['sku'] for p in data['products']} != expected:
        raise ValueError('Expected all eight approved products, including owner-confirmed Urea cream')
    for p in data['products']:
        days = 90 if p['sku'].endswith('-3M') else 30
        if (p['therapy_id'] != 'skin-care' or p['duration_months'] * 30 != days
                or p['supply_days_per_shipment'] != days or p['shipments_per_term'] != 1
                or p['grams_per_shipment'] != days or p['included_refills'] != 0
                or p['check_in_required'] is not False
                or p['source_billing_label'] != ('3 mo' if days == 90 else 'pack')):
            raise ValueError('Source quantity, billing or delivery contract mismatch: ' + p['sku'])
    return data


def prepare(existing):
    return prepare_batch(existing, load_catalog())


def install(path, apply=False):
    return install_batch(path, apply, catalog=load_catalog(), run_id=RUN_ID)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(install(args.database, args.apply)))
