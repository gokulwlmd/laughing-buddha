"""Append approved sublingual products to the ORIGINAL ED draft atomically.

Never publish, provision providers, replace existing prices, or create a second
ED template. Existing draft plans and variant metadata are retained verbatim.
"""
import argparse
import copy
import json
from pathlib import Path
import sqlite3
import time
from import_additional_masters import prepare as prepare_batch
from import_wellness_masters import CatalogView
from master import fingerprint
from catalog_contracts import validate_purchase_pairs

RUN_ID = 'owner-approved-original-ed-sublingual-20261026-v1'
THERAPY = 'erectile-dysfunction'
TEMPLATE = 'master-therapy-ed'
ALLOWED_UPDATES = {('therapy', THERAPY), ('template_draft', TEMPLATE), ('therapy_variant_catalog', THERAPY)}
EXPECTED = {'SILD-RDT-100MG': 10, 'TADA-RDT-5MG': 30, 'TADA-RDT-20MG': 10, 'VARD-RDT-25MG': 10}


def load_catalog():
    data = json.loads(Path(__file__).with_name('ed_sublingual_catalog.json').read_text())
    expected = {f'{prefix}-{m}M' for prefix in EXPECTED for m in (1, 3, 6, 12)}
    if len(data['products']) != 16 or {p['sku'] for p in data['products']} != expected:
        raise ValueError('Expected all 16 exact approved sublingual combinations')
    for p in data['products']:
        m = p['duration_months']; days = 30 if m == 1 else 90; count = m * 30 // days
        qty = EXPECTED[p['sku'].rsplit('-', 1)[0]]
        if (p['therapy_id'] != THERAPY or p['supply_days_per_shipment'] != days
                or p['shipments_per_term'] != count or p['included_refills'] != count - 1
                or p['check_in_required'] is not False or p['tablets_per_month'] != qty
                or p['tablets_per_shipment'] != qty * days // 30 or p['total_tablets'] != qty * m):
            raise ValueError('Source delivery contract mismatch: ' + p['sku'])
    return data


def prepare(existing):
    original = existing.get(('template_draft', TEMPLATE))
    variants = existing.get(('therapy_variant_catalog', THERAPY))
    if not original or not variants or original.get('therapy_id') != THERAPY:
        raise ValueError('Original ED draft and variant catalog are required')
    if not original.get('draft') or not original.get('enabled'):
        raise ValueError('Original ED template must be an enabled draft')
    catalog = load_catalog()
    pending = prepare_batch(existing, catalog)
    extra = pending.pop(('template_draft', 'master-therapy-ed-sublingual'))
    new_variants = pending.pop(('therapy_variant_catalog', 'ed-sublingual'))
    draft = copy.deepcopy(original)
    new_ids = {p['id'] for p in extra['plans']}
    if any(p['id'] in new_ids for p in draft['plans']):
        raise ValueError('Sublingual plan already present; reconcile before import')
    draft['plans'].extend(extra['plans'])
    view = CatalogView(copy.deepcopy(existing) | pending)
    _, guards, _, ops, _ = view.prepare_template_editor(draft)
    if guards or ops:
        raise ValueError('Draft extension cannot write provider objects')
    pending['template_draft', TEMPLATE] = draft
    updated = copy.deepcopy(variants)
    new_skus = {p['sku'] for p in new_variants['products']}
    if any(p['sku'] in new_skus for p in updated['products']):
        raise ValueError('Sublingual variants already present; reconcile before import')
    updated['products'].extend(new_variants['products'])
    updated.setdefault('source_extensions', []).append(dict(source=catalog['source'], price_basis=catalog['price_basis']))
    updated.setdefault('fixed_quantity_medications', {}).update({p['medication']:p['tablets_per_month'] for p in catalog['products']})
    updated['version'] = int(updated.get('version', 1)) + 1
    pending['therapy_variant_catalog', THERAPY] = updated
    return pending


def install(path, apply=False):
    path = Path(path).resolve(strict=True)
    db = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=10)
    try:
        db.execute('BEGIN IMMEDIATE' if apply else 'BEGIN')
        existing = {(k,i):json.loads(v) for k,i,v in db.execute('SELECT kind,id,data FROM admin_config')}
        catalog = load_catalog()
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='admin_setup_runs'").fetchone():
            row = db.execute('SELECT details FROM admin_setup_runs WHERE id=?', (RUN_ID,)).fetchone()
            if row:
                marker = json.loads(row[0])
                if marker['catalog_hash'] != fingerprint(catalog):
                    raise ValueError('Catalog changed since import')
                if any(tuple(k) not in existing for k in marker['created_records']):
                    raise ValueError('Incomplete import requires reconciliation')
                masters = [existing['master',p['sku']+s] for p in catalog['products'] for s in ('','-SUB')]
                validate_purchase_pairs(masters, [p['sku'] for p in catalog['products']])
                required = {p['sku']+s for p in catalog['products'] for s in ('','-SUB')}
                actual = {s for p in existing['template_draft',TEMPLATE]['plans'] for s in p['skus']}
                if not required <= actual:
                    raise ValueError('Original ED template no longer contains the imported variants')
                return dict(already_imported=True, created_records=0, master_skus=32)
        pending = prepare(existing)
        new = set(pending) - set(existing); updated = set(pending) & set(existing)
        if updated != ALLOWED_UPDATES:
            raise ValueError('Unexpected updates; reconcile original ED setup')
        if apply:
            db.execute('CREATE TABLE IF NOT EXISTS admin_setup_runs(id TEXT PRIMARY KEY,created REAL NOT NULL,details TEXT NOT NULL)')
            for (kind,key),value in pending.items():
                if (kind,key) in updated:
                    db.execute('UPDATE admin_config SET data=? WHERE kind=? AND id=?', (json.dumps(value),kind,key))
                else:
                    db.execute('INSERT INTO admin_config(kind,id,data) VALUES(?,?,?)', (kind,key,json.dumps(value)))
            marker = dict(catalog_hash=fingerprint(catalog),created_records=sorted(new),updated_records=sorted(updated),
                authorization='Owner approved 32 paired sublingual SKUs appended to the initial ED setup',provider_writes=0,payment_writes=0)
            db.execute('INSERT INTO admin_setup_runs VALUES(?,?,?)', (RUN_ID,time.time(),json.dumps(marker)))
            db.commit()
        return dict(applied=apply, master_skus=32, product_combinations=16, added_plans=4,
            template_id=TEMPLATE, total_template_plans=len(pending['template_draft',TEMPLATE]['plans']),
            refill_policies=32, planned_new_records=len(new), updated_records=len(updated),provider_writes=0,payment_writes=0)
    finally:
        db.rollback();db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(install(args.database,args.apply)))
