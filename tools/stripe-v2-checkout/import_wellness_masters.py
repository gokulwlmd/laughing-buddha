"""Add approved Hair Growth, NAD+ and Glutathione drafts, without provider writes.

Defaults to preview. Uses the target release's validators and an atomic additive
transaction. Existing records, site assignments and payment attempts are retained.
"""
import argparse
import copy
import json
from pathlib import Path
import sqlite3
import time

from master import MasterCatalog, fingerprint
from plans import PlanCatalog
from sites import SiteCatalog
from catalog_contracts import validate_purchase_pairs

RUN_ID = 'owner-approved-hair-nad-glutathione-v1'
THERAPIES = {'hair-growth': 'Hair Growth', 'nad-plus': 'NAD+', 'glutathione': 'Glutathione'}


class CatalogView(MasterCatalog, PlanCatalog, SiteCatalog):
    def __init__(self, records):
        self.saved = dict(records)

    def get(self, kind, key):
        return self.saved.get((kind, key))

    def records(self, kind):
        return [v for (k, _), v in self.saved.items() if k == kind]

    def local_fingerprint(self):
        return fingerprint(sorted((k, i, v) for (k, i), v in self.saved.items()))


def load_catalog():
    data = json.loads(Path(__file__).with_name('wellness_master_catalog.json').read_text())
    products = data['products']
    if len({p['sku'] for p in products}) != len(products):
        raise ValueError('Duplicate source SKU')
    for p in products:
        months, count, days = p['duration_months'], p['shipments_per_term'], p['supply_days_per_shipment']
        if (p['therapy_id'] not in THERAPIES or months not in (1, 3, 6, 12)
                or count != {1: 1, 3: 1, 6: 2, 12: 4}[months]
                or count * days != months * 30 or p['included_refills'] != count - 1
                or p['sku'].endswith('-SUB') or not p['source_row']):
            raise ValueError('Invalid source delivery contract: ' + p['sku'])
    return data


def prepare(existing):
    catalog = load_catalog()
    view, pending = CatalogView(existing), {}

    def add(kind, key, value):
        if (kind, key) in view.saved:
            raise ValueError('Existing record requires reconciliation: ' + kind + '/' + key)
        view.saved[kind, key] = value
        pending[kind, key] = value

    for therapy_id, name in THERAPIES.items():
        products = [p for p in catalog['products'] if p['therapy_id'] == therapy_id]
        treatments = {p['treatment_id']: p['name'] for p in products}
        therapy = {'id': therapy_id, 'name': name, 'enabled': True,
                   'treatments': [{'id': k, 'name': v} for k, v in treatments.items()]}
        add('therapy', therapy_id, view.prepare_plan('therapy', therapy)[0])
        for p in products:
            for recurring in (False, True):
                sku = p['sku'] + ('-SUB' if recurring else '')
                purchase = 'Subscription' if recurring else 'One-time'
                master = {'sku': sku, 'name': f"{p['name']} · {p['duration_months']}-month plan · {purchase}",
                    'category': name, 'therapy_id': therapy_id, 'treatment_id': p['treatment_id'],
                    'product_duration_months': p['duration_months'], 'currency': 'USD', 'enabled': True,
                    'planning_contract': {'charge': 'full_term_upfront', 'term_months': p['duration_months'],
                        'renewal_months': p['duration_months'] if recurring else None,
                        'shipments_per_term': p['shipments_per_term'],
                        'shipment_interval': p['supply_days_per_shipment'] if p['shipments_per_term'] > 1 else None,
                        'later_shipment_charge': '0.00'},
                    'offers': [{'id': 'upfront', 'name': 'Full-term upfront ' + purchase.lower(),
                                'price': p['price'], 'billing_models': []}]}
                value, guards, _, operations, _ = view.prepare_master('master', master)
                if guards or operations:
                    raise ValueError('Master draft must not write provider objects')
                add('master', sku, value)
                add('sku', sku, {k: value[k] for k in ('sku', 'name', 'product_id')})
        plans = []
        for months in sorted({p['duration_months'] for p in products}):
            selected = [p for p in products if p['duration_months'] == months]
            plan = {'id': f'{therapy_id}-{months}m', 'name': f'{name} · {months}-month plan',
                    'therapy_id': therapy_id, 'duration_months': months, 'enabled': True,
                    'skus': [sku for p in selected for sku in (p['sku'], p['sku'] + '-SUB')],
                    'payment_types': ['once', 'subscription'] + (['prepaid'] if any(p['shipments_per_term'] > 1 for p in selected) else [])}
            add('purchase_option', plan['id'], view.prepare_plan('purchase_option', plan)[0])
            plans.append(plan)
        template_id = 'master-therapy-' + therapy_id
        draft = {'id': template_id, 'name': 'Master Therapy · ' + name,
                 'title': 'Choose your ' + name + ' plan', 'therapy_id': therapy_id,
                 'plans': plans, 'draft': True, 'enabled': True}
        value, guards, _, operations, _ = view.prepare_template_editor(draft)
        if guards or operations:
            raise ValueError('Template draft must not write provider objects')
        add('template_draft', template_id, value['request'])
        variants = copy.deepcopy(products)
        for p in variants:
            p['purchase_skus'] = {'once': p['sku'], 'subscription': p['sku'] + '-SUB'}
        add('therapy_variant_catalog', therapy_id, {
            'version': 1, 'therapy_id': therapy_id, 'products': variants,
            'selection_order': ['format', 'treatment_id', 'duration_months', 'purchase_type'],
            'purchase_types': ['once', 'subscription'], 'source': catalog['source'],
            'reference_commit': catalog['reference_commit'], 'price_basis': catalog['price_basis'],
            'mapping_notes': catalog['mapping_notes'], 'excluded': catalog['excluded'],
            'activation': 'Draft. Verify site fulfillment mappings and billing before publication.'})
    validate_purchase_pairs([v for (k, _), v in pending.items() if k == 'master'],
                            [p['sku'] for p in catalog['products']])
    return pending


def install(path, apply=False):
    path = Path(path).resolve(strict=True)
    db = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=10)
    try:
        db.execute('BEGIN IMMEDIATE' if apply else 'BEGIN')
        existing = {(k, i): json.loads(v) for k, i, v in db.execute('SELECT kind,id,data FROM admin_config')}
        catalog = load_catalog()
        bases = [p['sku'] for p in catalog['products']]
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='admin_setup_runs'").fetchone():
            row = db.execute('SELECT details FROM admin_setup_runs WHERE id=?', (RUN_ID,)).fetchone()
            if row:
                marker = json.loads(row[0])
                if marker['catalog_hash'] != fingerprint(catalog):
                    raise ValueError('Catalog changed since import; reconcile explicitly')
                keys = [tuple(k) for k in marker['created_records']]
                if any(k not in existing for k in keys):
                    raise ValueError('Incomplete import requires reconciliation')
                validate_purchase_pairs([existing[k] for k in keys if k[0] == 'master'], bases)
                return {'already_imported': True, 'created_records': 0, 'master_skus': len(bases) * 2}
        pending = prepare(existing)
        if apply:
            db.execute('CREATE TABLE IF NOT EXISTS admin_setup_runs(id TEXT PRIMARY KEY,created REAL NOT NULL,details TEXT NOT NULL)')
            for (kind, key), value in pending.items():
                db.execute('INSERT INTO admin_config(kind,id,data) VALUES(?,?,?)', (kind, key, json.dumps(value)))
            details = {'authorization': 'Owner requested Hair Growth, NAD+ and Glutathione master setup',
                       'created_records': [list(k) for k in pending], 'catalog_hash': fingerprint(catalog),
                       'sticky_writes': 0, 'payment_writes': 0}
            db.execute('INSERT INTO admin_setup_runs VALUES(?,?,?)', (RUN_ID, time.time(), json.dumps(details)))
            db.commit()
        return {'applied': apply, 'master_skus': len(bases) * 2, 'product_combinations': len(bases),
                'therapies': len(THERAPIES), 'plans': sum(k == 'purchase_option' for k, _ in pending),
                'created_records': len(pending) if apply else 0, 'planned_new_records': len(pending),
                'checkout_templates': 'draft', 'sticky_writes': 0, 'payment_writes': 0}
    finally:
        db.rollback()
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(install(args.database, args.apply)))
