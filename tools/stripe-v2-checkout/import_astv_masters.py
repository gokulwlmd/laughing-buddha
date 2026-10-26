"""Add four ASTV 5-pack master drafts. Unknown delivery rules remain unset.

Uses runtime validators, no application startup and no provider writes.
"""
import argparse
import copy
import json
from pathlib import Path
import sqlite3
import time
from catalog_contracts import validate_purchase_pairs
from master import MasterCatalog, fingerprint
from plans import PlanCatalog
from sites import SiteCatalog

RUN_ID = 'owner-approved-astv-5pack-20261026-v1'
THERAPY = 'erectile-dysfunction'
PRODUCTS = [(1, 56595, '69.99'), (3, 56598, '291.00'),
            (6, 56602, '450.00'), (12, 56606, '900.00')]


class CatalogView(MasterCatalog, PlanCatalog, SiteCatalog):
    def __init__(self, records):
        self.saved = records

    def get(self, kind, key):
        return self.saved.get((kind, key))

    def records(self, kind):
        return [v for (k, _), v in self.saved.items() if k == kind]

    def local_fingerprint(self):
        return fingerprint(sorted((k, i, v) for (k, i), v in self.saved.items()))


def prepare(existing):
    view = CatalogView(copy.deepcopy(existing))
    pending = {}
    therapy = copy.deepcopy(view.get('therapy', THERAPY))
    if not therapy or not therapy.get('enabled'):
        raise ValueError('The existing ED therapy must be enabled')
    treatment = 'astv-5pack'
    if any(t['id'] == treatment for t in therapy['treatments']):
        raise ValueError('ASTV treatment already exists; reconcile before importing')
    therapy['treatments'].append({'id': treatment, 'name': '4-in-1 ED blend · 5-pack'})
    if 'revision' in therapy:
        therapy['revision'] += 1
    view.saved['therapy', THERAPY] = pending['therapy', THERAPY] = therapy

    def add(kind, key, value):
        if (kind, key) in view.saved:
            raise ValueError('Existing record requires reconciliation: ' + kind + '/' + key)
        view.saved[kind, key] = pending[kind, key] = value

    plans, variants = [], []
    for months, source_id, price in PRODUCTS:
        base = f'ASTV-5P-{months}M'
        for suffix in ('', '-SUB'):
            sku = base + suffix
            payload = dict(sku=sku, name=f'4-in-1 ED blend · 5-pack · {months}-month · ' + ('Subscription' if suffix else 'One-time'),
                therapy_id=THERAPY, treatment_id=treatment, category='Erectile Dysfunction (ED)',
                product_duration_months=months, currency='USD', enabled=True,
                planning_contract=dict(charge='full_term_upfront', term_months=months,
                    renewal_months=months if suffix else None,
                    shipments_per_term=1 if months == 1 else None,
                    shipment_interval=None, later_shipment_charge='0.00'),
                offers=[dict(id='upfront', name='Full-term upfront', price=price, billing_models=[])])
            value, guards, _, operations, _ = view.prepare_master('master', payload)
            if guards or operations:
                raise ValueError('Drafts must not access Sticky')
            add('master', sku, value)
            add('sku', sku, {k: value[k] for k in ('sku', 'name', 'product_id')})
        plan = dict(id=f'astv-5pack-{months}m', name=f'4-in-1 ED blend · 5-pack · {months}-month',
            therapy_id=THERAPY, duration_months=months, enabled=True,
            skus=[base, base + '-SUB'], payment_types=['once', 'subscription'])
        add('purchase_option', plan['id'], view.prepare_plan('purchase_option', plan)[0])
        plans.append(plan)
        variants.append(dict(sku=base, treatment_id=treatment, name='Apomorphine / Sildenafil / Tadalafil / Vardenafil',
            duration_months=months, source_product_id=source_id, source_package='5 packets (10 mL)',
            strength=None, supply_days_per_shipment=30 if months == 1 else None,
            shipments_per_term=1 if months == 1 else None, included_refills=0 if months == 1 else None,
            check_in_required=False if months == 1 else None,
            source_row=69 if months == 1 else None,
            purchase_skus={'once': base, 'subscription': base + '-SUB'}))
    draft = dict(id='master-therapy-astv-5pack', name='Master Therapy · 4-in-1 ED blend · 5-pack',
        title='Choose your 4-in-1 ED plan', therapy_id=THERAPY, plans=plans, draft=True, enabled=True)
    value, guards, _, operations, _ = view.prepare_template_editor(draft)
    if guards or operations:
        raise ValueError('Template must remain a local draft')
    add('template_draft', draft['id'], value['request'])
    add('therapy_variant_catalog', 'astv-5pack', dict(version=1, therapy_id=THERAPY, products=variants,
        selection_order=['duration_months', 'purchase_type'], purchase_types=['once', 'subscription'],
        source='Sticky product readback 2026-10-26; Catalog sheet row 69 for 1-month delivery rules.',
        price_basis='Editable starting prices from the four inspected Sticky product records; not final brand prices.',
        activation='Draft. Confirm 3/6/12-month shipment quantities, schedules and check-in rules, full ingredient strengths, and site provider mappings before publishing.'))
    validate_purchase_pairs([v for (k, _), v in pending.items() if k == 'master'],
                            [f'ASTV-5P-{m}M' for m, _, _ in PRODUCTS])
    return pending


def install(path, apply=False):
    path = Path(path).resolve(strict=True)
    with sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=10) as db:
        db.execute('BEGIN IMMEDIATE' if apply else 'BEGIN')
        existing = {(k, i): json.loads(v) for k, i, v in db.execute('SELECT kind,id,data FROM admin_config')}
        has_runs = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='admin_setup_runs'").fetchone()
        marker = db.execute('SELECT details FROM admin_setup_runs WHERE id=?', (RUN_ID,)).fetchone() if has_runs else None
        if marker:
            saved = json.loads(marker[0])
            if saved['catalog_hash'] != fingerprint(PRODUCTS):
                raise ValueError('ASTV source changed; reconcile before importing')
            if any(tuple(k) not in existing for k in saved['created_records']):
                raise ValueError('Incomplete ASTV import requires reconciliation')
            return dict(already_imported=True, master_skus=8)
        pending = prepare(existing)
        if apply:
            db.execute('CREATE TABLE IF NOT EXISTS admin_setup_runs(id TEXT PRIMARY KEY,created REAL NOT NULL,details TEXT NOT NULL)')
            for (kind, key), value in pending.items():
                if (kind, key) == ('therapy', THERAPY):
                    db.execute('UPDATE admin_config SET data=? WHERE kind=? AND id=?', (json.dumps(value), kind, key))
                else:
                    db.execute('INSERT INTO admin_config(kind,id,data) VALUES(?,?,?)', (kind, key, json.dumps(value)))
            details = dict(created_records=[k for k in pending if k not in existing],
                catalog_hash=fingerprint(PRODUCTS), provider_writes=0, delivery_rules_pending=[3, 6, 12])
            db.execute('INSERT INTO admin_setup_runs VALUES(?,?,?)', (RUN_ID, time.time(), json.dumps(details)))
        return dict(applied=apply, master_skus=8, plans=4, template_drafts=1,
                    new_records=len(pending)-1, delivery_rules_pending=[3, 6, 12], provider_writes=0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(install(args.database, args.apply)))
