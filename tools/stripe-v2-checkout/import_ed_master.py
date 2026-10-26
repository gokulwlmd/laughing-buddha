"""Add the approved ED master catalog without provider writes or app restarts.

Uses the running release's validators, not app.create_app (which has startup
side effects). Adds paired master configuration or repairs the recorded v1 ED
draft atomically. Refuses assigned/published ED; preserves edited draft prices
and shipment schedules. Unrelated records are never replaced. Defaults to preview.
"""
import argparse
import copy
import json
from pathlib import Path
import sqlite3
import time

from master import MasterCatalog, MasterSKU, fingerprint, planned_product_setup
from catalog_contracts import validate_purchase_pairs
from plans import PlanCatalog
from sites import SiteCatalog

LEGACY_RUN_ID = 'owner-approved-ed-master-v1'
RUN_ID = 'owner-approved-ed-master-purchase-pairs-v2'
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


def _legacy_records(existing):
    """Reconstruct v1 for guarded repair only; never install this snapshot."""
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


def prepare(existing):
    legacy = _legacy_records(existing)
    result = {k: v for k, v in legacy.items() if k[0] not in ('master', 'sku', 'purchase_option', 'template_draft', 'therapy_variant_catalog')}
    view = CatalogView(dict(existing) | result)
    for (kind, sku), old in legacy.items():
        if kind != 'master':
            continue
        for recurring in (False, True):
            payload = copy.deepcopy({k: v for k, v in old.items() if k in MasterSKU.model_fields})
            payload['sku'] = sku + ('-SUB' if recurring else '')
            payload['name'] += ' · ' + ('Subscription' if recurring else 'One-time')
            payload['planning_contract']['renewal_months'] = payload['product_duration_months'] if recurring else None
            payload['offers'][0]['name'] = 'Full-term upfront ' + ('subscription' if recurring else 'one-time')
            data, guards, _, operations, _ = view.prepare_master('master', payload)
            if guards or operations:
                raise ValueError('Master pairs cannot write provider objects')
            result['master', data['sku']] = data
            result['sku', data['sku']] = {k: data[k] for k in ('sku', 'name', 'product_id')}
    view.saved.update(result)
    plans = []
    for (kind, key), old in legacy.items():
        if kind != 'purchase_option':
            continue
        plan = {k: copy.deepcopy(v) for k, v in old.items() if k != 'revision'}
        plan['skus'] = [variant for sku in old['skus'] for variant in (sku, sku + '-SUB')]
        plan['payment_types'] = ['once', 'subscription'] + (['prepaid'] if plan['duration_months'] >= 6 else [])
        result[kind, key] = view.prepare_plan(kind, plan)[0]
        plans.append(plan)
    view.saved.update(result)
    draft = copy.deepcopy(legacy['template_draft', TEMPLATE_ID])
    draft['plans'] = plans
    result['template_draft', TEMPLATE_ID] = view.prepare_template_editor(draft)[0]['request']
    variants = copy.deepcopy(legacy['therapy_variant_catalog', THERAPY_ID])
    variants.update(version=2, purchase_types=['once', 'subscription'])
    variants['selection_order'].append('purchase_type')
    for product in variants['products']:
        product['purchase_skus'] = {'once': product['sku'], 'subscription': product['sku'] + '-SUB'}
    result['therapy_variant_catalog', THERAPY_ID] = variants
    if set(result) & set(existing):
        raise ValueError('Existing ED record requires reconciliation; nothing overwritten')
    validate_purchase_pairs([v for (k, _), v in result.items() if k == 'master'], [p['sku'] for p in load_catalog()['products']])
    return result


def _repair_v1(existing, marker):
    """Correct only the recorded, unassigned ED draft; preserve edited prices/schedules."""
    legacy = _legacy_records({})
    if {tuple(key) for key in marker['created_records']} != set(legacy):
        raise ValueError('Legacy ED import marker differs; reconcile before repair')
    bases = {p['sku'] for p in load_catalog()['products']}
    identifiers = bases | {s + '-SUB' for s in bases} | {THERAPY_ID, TEMPLATE_ID}
    identifiers.update(key for kind, key in legacy if kind == 'purchase_option')

    def references_ed(value):
        if isinstance(value, str):
            return value in identifiers
        if isinstance(value, dict):
            return any(references_ed(v) for v in value.values())
        if isinstance(value, list):
            return any(references_ed(v) for v in value)
        return False

    for (kind, key), value in existing.items():
        if (kind, key) not in legacy and references_ed(value):
            raise ValueError('ED is referenced outside its draft; reconcile before changing billing: ' + kind)

    def comparable(kind, value):
        value = copy.deepcopy(value)
        value.pop('revision', None)
        if kind == 'master':
            value.pop('product_setup', None)
            for offer in value.get('offers', []):
                offer.pop('price', None)
            for field in ('shipments_per_term', 'shipment_interval'):
                value.get('planning_contract', {}).pop(field, None)
        return value

    for key, baseline in legacy.items():
        current = existing.get(key)
        if current is None or comparable(key[0], current) != comparable(key[0], baseline):
            raise ValueError('ED draft changed outside price/shipment edits; reconcile: ' + '/'.join(key))
        if key[0] == 'master':
            MasterSKU.model_validate({k: v for k, v in current.items() if k in MasterSKU.model_fields})
            if current.get('product_setup') != planned_product_setup(current):
                raise ValueError('ED product setup differs from its contract: ' + key[1])
    pending = prepare({k: v for k, v in existing.items() if k not in legacy})
    for sku in bases:
        old = existing['master', sku]
        for target in (sku, sku + '-SUB'):
            data = pending['master', target]
            data['offers'][0]['price'] = old['offers'][0]['price']
            for field in ('shipments_per_term', 'shipment_interval'):
                data['planning_contract'][field] = old['planning_contract'][field]
            data['product_setup'] = planned_product_setup(data)
            data['revision'] = old.get('revision', 1) + 1 if target == sku else 1
    for key in legacy:
        if key[0] == 'purchase_option':
            pending[key]['revision'] = existing[key].get('revision', 1) + 1
    validate_purchase_pairs([v for (k, _), v in pending.items() if k == 'master'], bases)
    return pending


def install(path, apply=False):
    path = Path(path).resolve(strict=True)
    # mode=rw refuses to manufacture a new database at a mistyped destination.
    db = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=10)
    try:
        db.execute('BEGIN IMMEDIATE' if apply else 'BEGIN')
        existing = {(k, i): json.loads(v) for k, i, v in db.execute('SELECT kind,id,data FROM admin_config')}
        legacy_marker = None
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='admin_setup_runs'").fetchone():
            row = db.execute('SELECT details FROM admin_setup_runs WHERE id=?', (RUN_ID,)).fetchone()
            if row:
                marker = json.loads(row[0])
                if any(tuple(key) not in existing for key in marker['created_records']):
                    raise ValueError('ED import is incomplete; reconcile without overwriting')
                validate_purchase_pairs([existing[tuple(key)] for key in marker['created_records'] if key[0] == 'master'], [p['sku'] for p in load_catalog()['products']])
                return {'already_imported': True, 'created_records': 0, 'master_skus': 176}
            row = db.execute('SELECT details FROM admin_setup_runs WHERE id=?', (LEGACY_RUN_ID,)).fetchone()
            legacy_marker = json.loads(row[0]) if row else None
        pending = _repair_v1(existing, legacy_marker) if legacy_marker else prepare(existing)
        created = set(pending) - set(existing)
        updated = {key for key in pending if key in existing and pending[key] != existing[key]}
        if apply:
            db.execute('CREATE TABLE IF NOT EXISTS admin_setup_runs(id TEXT PRIMARY KEY,created REAL NOT NULL,details TEXT NOT NULL)')
            for (kind, key), value in pending.items():
                if (kind, key) in updated:
                    db.execute('UPDATE admin_config SET data=? WHERE kind=? AND id=?', (json.dumps(value), kind, key))
                elif (kind, key) in created:
                    db.execute('INSERT INTO admin_config(kind,id,data) VALUES(?,?,?)', (kind, key, json.dumps(value)))
            details = {'authorization': 'Owner requested base one-time and -SUB recurring ED pairs; correction of unassigned draft only',
                       'created_records': [list(key) for key in pending],
                       'added_records': [list(key) for key in sorted(created)],
                       'updated_records': [list(key) for key in sorted(updated)],
                       'catalog_hash': fingerprint(load_catalog()), 'sticky_writes': 0, 'payment_writes': 0}
            db.execute('INSERT INTO admin_setup_runs VALUES(?,?,?)', (RUN_ID, time.time(), json.dumps(details)))
            db.commit()
        return {'applied': apply, 'master_skus': 176, 'product_combinations': 88, 'treatments': 3, 'plans': 12,
                'created_records': len(created) if apply else 0, 'updated_records': len(updated) if apply else 0,
                'planned_new_records': len(created), 'planned_updates': len(updated),
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
