"""Atomic, additive import of the four approved Oct 26 master product families.

No Sticky/provider writes. Existing templates, prices, sites and care snapshots
are preserved. Existing therapies only gain the newly approved treatments.
"""
import argparse
import copy
import json
from pathlib import Path
import sqlite3
import time
from import_wellness_masters import CatalogView
from master import fingerprint
from plans import Therapy
from catalog_contracts import validate_purchase_pairs
from catalog_refill_policies import proposed_policy, source_binding
from refill_rules import SaveRefillRules, validate_included_policy

RUN_ID = 'owner-approved-additional-master-families-20261026-v1'


def load_catalog():
    data = json.loads(Path(__file__).with_name('additional_master_catalog.json').read_text())
    products = data['products']
    if len(products) != 15 or len({p['sku'] for p in products}) != 15:
        raise ValueError('Expected 15 unique approved source combinations')
    families = {f['id']: f for f in data['families']}
    for p in products:
        m, count, days = p['duration_months'], p['shipments_per_term'], p['supply_days_per_shipment']
        if (p['therapy_id'] != families[p['family_id']]['therapy_id'] or m not in (1, 3, 6, 12)
                or count != {1: 1, 3: 1, 6: 2, 12: 4}[m] or count * days != m * 30
                or p['included_refills'] != count - 1 or p['check_in_required'] is not False
                or p['sku'].endswith('-SUB')):
            raise ValueError('Invalid source delivery contract: ' + p['sku'])
    return data


def prepare(existing):
    catalog = load_catalog()
    view, pending = CatalogView(copy.deepcopy(existing)), {}

    def add(kind, key, value):
        if (kind, key) in view.saved:
            raise ValueError('Existing record requires reconciliation: ' + kind + '/' + key)
        view.saved[kind, key] = pending[kind, key] = value

    for family in catalog['families']:
        fid, tid, name = family['id'], family['therapy_id'], family['name']
        products = [p for p in catalog['products'] if p['family_id'] == fid]
        old = view.get('therapy', tid)
        therapy = copy.deepcopy(old) if old else dict(id=tid, name=family['therapy_name'], enabled=True, treatments=[])
        if not therapy['enabled']:
            raise ValueError('Existing therapy is disabled; reconcile explicitly: ' + tid)
        treatments = {p['treatment_id']: p['name'] for p in products}
        for treatment, label in treatments.items():
            if any(t['id'] == treatment for t in therapy['treatments']):
                raise ValueError('Treatment already exists; reconcile explicitly: ' + treatment)
            therapy['treatments'].append({'id': treatment, 'name': label})
        # Validate without discarding extension fields in the existing record.
        view.prepare_plan('therapy', {k: v for k, v in therapy.items() if k in Therapy.model_fields})
        if old and 'revision' in old:
            therapy['revision'] += 1
        view.saved['therapy', tid] = pending['therapy', tid] = therapy
        for p in products:
            for recurring in (False, True):
                sku = p['sku'] + ('-SUB' if recurring else '')
                purchase = 'Subscription' if recurring else 'One-time'
                master = dict(sku=sku, name=f"{name} · {p['duration_months']}-month plan · {purchase}",
                    category=family['therapy_name'], therapy_id=tid, treatment_id=p['treatment_id'],
                    product_duration_months=p['duration_months'], currency='USD', enabled=True,
                    planning_contract=dict(charge='full_term_upfront', term_months=p['duration_months'],
                        renewal_months=p['duration_months'] if recurring else None,
                        shipments_per_term=p['shipments_per_term'],
                        shipment_interval=p['supply_days_per_shipment'] if p['shipments_per_term'] > 1 else None,
                        later_shipment_charge='0.00'),
                    offers=[dict(id='upfront', name='Full-term upfront ' + purchase.lower(), price=p['price'], billing_models=[])])
                value, guards, _, ops, _ = view.prepare_master('master', master)
                if guards or ops:
                    raise ValueError('Master draft must not write provider objects')
                add('master', sku, value)
                add('sku', sku, {k: value[k] for k in ('sku', 'name', 'product_id')})
                policy = proposed_policy(p, sku)
                body = SaveRefillRules.model_validate({k: v for k, v in policy.items() if k not in ('sku', 'revision')} | {'expected_revision': 0})
                validate_included_policy(body, source_binding(sku), value['product_setup'])
                add('refill_policy', sku, policy)
        plans = []
        for p in products:
            m = p['duration_months']
            plan = dict(id=f'{fid}-{m}m', name=f'{name} · {m}-month plan', therapy_id=tid,
                duration_months=m, enabled=True, skus=[p['sku'], p['sku'] + '-SUB'],
                payment_types=['once', 'subscription'] + (['prepaid'] if p['shipments_per_term'] > 1 else []))
            add('purchase_option', plan['id'], view.prepare_plan('purchase_option', plan)[0])
            plans.append(plan)
        draft = dict(id='master-therapy-' + fid, name='Master Therapy · ' + name,
            title='Choose your ' + name + ' plan', therapy_id=tid, plans=plans, draft=True, enabled=True)
        value, guards, _, ops, _ = view.prepare_template_editor(draft)
        if guards or ops:
            raise ValueError('Template draft must not write provider objects')
        add('template_draft', draft['id'], value['request'])
        # Product-family metadata is separate: old therapy variant collections
        # and their historical exclusions remain untouched.
        add('therapy_variant_catalog', fid, dict(version=1, therapy_id=tid, family_id=fid,
            products=[dict(p, purchase_skus={'once': p['sku'], 'subscription': p['sku'] + '-SUB'}) for p in products],
            selection_order=['treatment_id', 'duration_months', 'purchase_type'],
            purchase_types=['once', 'subscription'], source=catalog['source'], price_basis=catalog['price_basis'],
            activation='Draft. Confirm selling prices and site payment mappings before publication.'))
    validate_purchase_pairs([v for (k, _), v in pending.items() if k == 'master'], [p['sku'] for p in catalog['products']])
    return pending


def install(path, apply=False):
    path = Path(path).resolve(strict=True)
    db = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=10)
    try:
        db.execute('BEGIN IMMEDIATE' if apply else 'BEGIN')
        existing = {(k, i): json.loads(v) for k, i, v in db.execute('SELECT kind,id,data FROM admin_config')}
        catalog = load_catalog()
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='admin_setup_runs'").fetchone():
            row = db.execute('SELECT details FROM admin_setup_runs WHERE id=?', (RUN_ID,)).fetchone()
            if row:
                marker = json.loads(row[0])
                if marker['catalog_hash'] != fingerprint(catalog):
                    raise ValueError('Catalog changed since import; reconcile explicitly')
                keys = [tuple(k) for k in marker['created_records']]
                if any(k not in existing for k in keys):
                    raise ValueError('Incomplete import requires reconciliation')
                validate_purchase_pairs([existing[k] for k in keys if k[0] == 'master'], [p['sku'] for p in catalog['products']])
                return dict(already_imported=True, created_records=0, master_skus=30)
        pending = prepare(existing)
        new = [k for k in pending if k not in existing]
        updated = [k for k in pending if k in existing]
        if apply:
            db.execute('CREATE TABLE IF NOT EXISTS admin_setup_runs(id TEXT PRIMARY KEY,created REAL NOT NULL,details TEXT NOT NULL)')
            for (kind, key), value in pending.items():
                if (kind, key) in existing:
                    if kind != 'therapy':
                        raise ValueError('Only therapy treatment additions may update existing records')
                    db.execute('UPDATE admin_config SET data=? WHERE kind=? AND id=?', (json.dumps(value), kind, key))
                else:
                    db.execute('INSERT INTO admin_config(kind,id,data) VALUES(?,?,?)', (kind, key, json.dumps(value)))
            marker = dict(catalog_hash=fingerprint(catalog), created_records=new, updated_records=updated,
                authorization='Owner approved exact source SKUs plus -SUB for PT141 nasal, NAD RDT, SERM RDT500mcg and Sertraline25mg',
                provider_writes=0, payment_writes=0)
            db.execute('INSERT INTO admin_setup_runs VALUES(?,?,?)', (RUN_ID, time.time(), json.dumps(marker)))
            db.commit()
        return dict(applied=apply, master_skus=30, product_combinations=15, plans=15, template_drafts=4,
            refill_policies=30, planned_new_records=len(new), updated_therapies=len(updated), provider_writes=0, payment_writes=0)
    finally:
        db.rollback()
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(install(args.database, args.apply)))
