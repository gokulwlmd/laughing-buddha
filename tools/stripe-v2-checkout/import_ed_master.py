"""Add the approved ED master catalog without provider writes or app restarts.

Uses the running release's validators, not app.create_app (which has startup
side effects). Only adds admin configuration and an audit marker atomically.
Existing records and owner edits are never replaced. Defaults to preview.
"""
import argparse
import json
from pathlib import Path
import sqlite3
import time

from master import MasterCatalog, fingerprint
from plans import PlanCatalog
from sites import SiteCatalog

RUN_ID = 'owner-approved-ed-master-v1'
THERAPY_ID = 'erectile-dysfunction'
TEMPLATE_ID = 'master-therapy-ed'
MEDICATIONS = [
    ('sildenafil', 'Sildenafil', ('50', '100'), (6, 8, 10, 12, 14)),
    ('tadalafil-daily', 'Tadalafil Daily', ('2.5', '5'), (30,)),
    ('tadalafil-as-needed', 'Tadalafil as needed', ('10', '20'), (6, 8, 10, 12, 14)),
]


class CatalogView(MasterCatalog, PlanCatalog, SiteCatalog):
    """No network client: catalog drafts must never contact a provider."""
    def __init__(self, records):
        self.saved = records

    def get(self, kind, key):
        return self.saved.get((kind, key))

    def records(self, kind):
        return [v for (k, _), v in self.saved.items() if k == kind]

    def local_fingerprint(self):
        return fingerprint(sorted((k, i, v) for (k, i), v in self.saved.items()))


def load_catalog():
    catalog = json.loads(Path(__file__).with_name('ed_master_catalog.json').read_text())
    products = catalog['products']
    expected = {(med, dose, quantity, months) for med, _, doses, quantities in MEDICATIONS
                for dose in doses for quantity in quantities for months in (1, 3, 6, 12)}
    actual = set()
    for p in products:
        key = (p['medication'], p['strength_mg'], p['tablets_per_month'], p['duration_months'])
        if key in actual or key not in expected:
            raise ValueError('Duplicate or unsupported ED combination')
        actual.add(key)
        drug = 'SILD' if p['medication'] == 'sildenafil' else 'TADA'
        sku = f"{drug}-{p['strength_mg']}MG-{p['total_tablets']}-{p['tablets_per_month']}-{p['duration_months']}B"
        count = p['shipments_per_term']
        if (p['sku'] != sku or p['total_tablets'] != p['tablets_per_month'] * p['duration_months']
                or p['tablets_per_shipment'] * count != p['total_tablets']
                or p['supply_days_per_shipment'] * count != p['duration_months'] * 30
                or count != {1: 1, 3: 1, 6: 2, 12: 4}[p['duration_months']]
                or p['included_refills'] != count - 1):
            raise ValueError('Invalid SKU or fulfillment matrix: ' + p['sku'])
    if actual != expected or len(products) != 88:
        raise ValueError('ED catalog must contain all 88 approved combinations')
    return catalog


def prepare(existing):
    catalog = load_catalog()
    view = CatalogView(dict(existing))
    pending = {}

    def add(kind, key, value):
        if (kind, key) in view.saved:
            raise ValueError('Existing record requires reconciliation; nothing overwritten: ' + kind + '/' + key)
        pending[(kind, key)] = value
        view.saved[(kind, key)] = value

    therapy = {'id': THERAPY_ID, 'name': 'Erectile Dysfunction (ED)', 'enabled': True,
               'treatments': [{'id': med, 'name': name} for med, name, _, _ in MEDICATIONS]}
    add('therapy', THERAPY_ID, view.prepare_plan('therapy', therapy)[0])
    names = dict((med, name) for med, name, _, _ in MEDICATIONS)
    for p in catalog['products']:
        months = p['duration_months']
        master = {
            'sku': p['sku'],
            'name': f"{names[p['medication']]} · {p['strength_mg']} mg · {p['tablets_per_month']} tablets/month · {months}-month plan",
            'category': therapy['name'], 'therapy_id': THERAPY_ID,
            'treatment_id': p['medication'], 'product_duration_months': months,
            'currency': 'USD', 'enabled': True,
            'planning_contract': {'charge': 'full_term_upfront', 'term_months': months,
                'renewal_months': months, 'shipments_per_term': p['shipments_per_term'],
                'shipment_interval': p['supply_days_per_shipment'] if p['shipments_per_term'] > 1 else None,
                'later_shipment_charge': '0.00'},
            'offers': [{'id': 'upfront', 'name': 'Full-term upfront subscription',
                        'price': p['price'], 'billing_models': []}],
        }
        data, guards, _, operations, _ = view.prepare_master('master', master)
        if guards or operations:
            raise ValueError('ED master import cannot write provider objects')
        add('master', p['sku'], data)
        add('sku', p['sku'], {k: data[k] for k in ('sku', 'name', 'product_id')})

    plans = []
    # Keep each medication's variants together and below the existing 20-SKU
    # plan limit (10 as-needed variants / 2 daily variants per duration).
    for med, name, _, _ in MEDICATIONS:
        for months in (1, 3, 6, 12):
            plan = {'id': f'ed-{med}-{months}m', 'name': f'{name} · {months}-month plan',
                    'therapy_id': THERAPY_ID, 'duration_months': months,
                    'skus': [p['sku'] for p in catalog['products']
                             if p['medication'] == med and p['duration_months'] == months],
                    'payment_types': ['subscription', 'prepaid'] if months >= 6 else ['subscription'],
                    'enabled': True}
            validated = view.prepare_plan('purchase_option', plan)[0]
            add('purchase_option', plan['id'], validated)
            plans.append(plan)
    draft = {'id': TEMPLATE_ID, 'name': 'Master Therapy · Erectile Dysfunction (ED)',
             'title': 'Choose your ED treatment', 'therapy_id': THERAPY_ID,
             'plans': plans, 'draft': True, 'enabled': True}
    validated, guards, _, operations, _ = view.prepare_template_editor(draft)
    if guards or operations:
        raise ValueError('ED template import cannot write provider objects')
    add('template_draft', TEMPLATE_ID, validated['request'])
    # Structured variants are retained independently of editable price records.
    # They are a master-catalog contract, not a published patient API.
    add('therapy_variant_catalog', THERAPY_ID, catalog | {
        'therapy_id': THERAPY_ID,
        'selection_order': ['medication', 'strength_mg', 'tablets_per_month', 'duration_months'],
        'fixed_quantity_medications': {'tadalafil-daily': 30},
        'activation': 'Draft; verify site-specific provider, billing and fulfillment mappings before publishing',
    })
    return pending


def install(path, apply=False):
    path = Path(path).resolve(strict=True)
    # mode=rw refuses to manufacture a new database at a mistyped destination.
    db = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=10)
    try:
        db.execute('BEGIN IMMEDIATE' if apply else 'BEGIN')
        existing = {(k, i): json.loads(v) for k, i, v in db.execute('SELECT kind,id,data FROM admin_config')}
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='admin_setup_runs'").fetchone():
            row = db.execute('SELECT details FROM admin_setup_runs WHERE id=?', (RUN_ID,)).fetchone()
            if row:
                marker = json.loads(row[0])
                if any(tuple(key) not in existing for key in marker['created_records']):
                    raise ValueError('ED import is incomplete; reconcile without overwriting')
                return {'already_imported': True, 'created_records': 0, 'master_skus': 88}
        pending = prepare(existing)
        if apply:
            db.execute('CREATE TABLE IF NOT EXISTS admin_setup_runs(id TEXT PRIMARY KEY,created REAL NOT NULL,details TEXT NOT NULL)')
            for (kind, key), value in pending.items():
                db.execute('INSERT INTO admin_config(kind,id,data) VALUES(?,?,?)', (kind, key, json.dumps(value)))
            details = {'authorization': 'Owner requested Anuwell ED setup as a master therapy',
                       'created_records': [list(key) for key in pending],
                       'catalog_hash': fingerprint(load_catalog()), 'sticky_writes': 0, 'payment_writes': 0}
            db.execute('INSERT INTO admin_setup_runs VALUES(?,?,?)', (RUN_ID, time.time(), json.dumps(details)))
            db.commit()
        return {'applied': apply, 'master_skus': 88, 'treatments': 3, 'plans': 12,
                'created_records': len(pending) if apply else 0, 'planned_records': len(pending),
                'checkout_template': 'draft', 'sticky_writes': 0, 'payment_writes': 0}
    finally:
        db.rollback()
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(install(args.database, args.apply)))
