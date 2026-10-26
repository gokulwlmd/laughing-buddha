"""Approved next catalog batch: monthly gels, oral/skin products and NAD variants."""
import argparse
import json
from pathlib import Path
from import_additional_masters import prepare as prepare_batch, install as install_batch

RUN_ID = 'owner-approved-next-master-families-20261026-v1'


def load_catalog():
    catalog = json.loads(Path(__file__).with_name('next_master_catalog.json').read_text())
    products = catalog['products']
    if len(products) != 25 or len({p['sku'] for p in products}) != 25:
        raise ValueError('Expected 25 unique approved source combinations')
    families = {f['id']: f for f in catalog['families']}
    for p in products:
        months, count, days = p['duration_months'], p['shipments_per_term'], p['supply_days_per_shipment']
        if (p['therapy_id'] != families[p['family_id']]['therapy_id'] or months not in (1, 3, 6, 12)
                or count * days != months * 30 or p['included_refills'] != count - 1
                or p['check_in_required'] is not False or p['sku'].endswith('-SUB')):
            raise ValueError('Invalid source contract: ' + p['sku'])
        expected_days = 30 if p['family_id'] == 'womens-arousal' or months == 1 else 90
        if days != expected_days:
            raise ValueError('Delivery interval differs from source: ' + p['sku'])
    return catalog


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
