"""Add reviewed catalog recipes and non-publishable clarification drafts atomically.

No Sticky writes. Unknown products are review records, never executable SKUs.
Existing masters, assignments, prices, orders and templates remain untouched.
"""
import argparse
import json
import sqlite3
import time
from pathlib import Path
from import_additional_masters import prepare as prepare_recipes
from master import fingerprint
from catalog_contracts import validate_purchase_pairs

RUN_ID = 'owner-approved-remaining-catalog-20261026-v1'


def load_catalog():
    data = json.loads(Path(__file__).with_name('remaining_master_catalog.json').read_text())
    products = data['products']
    if len({p['sku'] for p in products}) != len(products):
        raise ValueError('Duplicate exact SKU in new recipes')
    review = {p['source_row']: p for p in data['review']}
    for p in products:
        r = review[p['source_row']]
        if (r['status'] != 'Finalized structure' or r['sku'] != p['sku']
                or p['shipments_per_term'] * p['supply_days_per_shipment'] != p['duration_months'] * 30
                or p['included_refills'] != p['shipments_per_term'] - 1
                or p['check_in_required'] != (r['check_in_required'] == 'Yes')):
            raise ValueError('Unresolved or inconsistent recipe: ' + p['sku'])
    return data


def prepare(existing):
    data = load_catalog()
    pending = prepare_recipes(existing, data)
    for r in data['review']:
        key = ('catalog_review', 'catalog-oct23-row-' + str(r['source_row']))
        if key in existing:
            raise ValueError('Review record already exists; reconcile explicitly')
        pending[key] = dict(r, id=key[1], enabled=False, draft=True,
                            record_type='source_review', publication_blocked=True)
    return pending


def install(path, apply=False):
    path = Path(path).resolve(strict=True)
    db = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=30)
    try:
        db.execute('BEGIN IMMEDIATE' if apply else 'BEGIN')
        existing = {(k, i): json.loads(v) for k, i, v in db.execute('SELECT kind,id,data FROM admin_config')}
        data = load_catalog()
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='admin_setup_runs'").fetchone():
            row = db.execute('SELECT details FROM admin_setup_runs WHERE id=?', (RUN_ID,)).fetchone()
            if row:
                marker = json.loads(row[0])
                if marker['catalog_hash'] != fingerprint(data) or any(tuple(k) not in existing for k in marker['created_records']):
                    raise ValueError('Catalog import requires reconciliation')
                validate_purchase_pairs([existing['master', p['sku'] + s] for p in data['products'] for s in ('', '-SUB')], [p['sku'] for p in data['products']])
                return dict(already_imported=True, created_records=0)
        pending = prepare(existing)
        new = [k for k in pending if k not in existing]
        updated = [k for k in pending if k in existing]
        if any(k != 'therapy' for k, _ in updated):
            raise ValueError('Only additive therapy changes are allowed')
        if apply:
            db.execute('CREATE TABLE IF NOT EXISTS admin_setup_runs(id TEXT PRIMARY KEY,created REAL NOT NULL,details TEXT NOT NULL)')
            for (kind, key), value in pending.items():
                if (kind, key) in existing:
                    db.execute('UPDATE admin_config SET data=? WHERE kind=? AND id=?', (json.dumps(value), kind, key))
                else:
                    db.execute('INSERT INTO admin_config VALUES(?,?,?)', (kind, key, json.dumps(value)))
            db.execute('INSERT INTO admin_setup_runs VALUES(?,?,?)', (RUN_ID, time.time(), json.dumps(dict(
                catalog_hash=fingerprint(data), created_records=new, updated_records=updated,
                authorization='Owner approved clear catalog recipes and disabled clarification drafts; no provider changes.',
                provider_writes=0, payment_writes=0))))
            db.commit()
        return dict(applied=apply, new_master_skus=len(data['products'])*2,
                    templates=len(data['families']), review_rows=len(data['review']),
                    clarification_drafts=sum(r['status']=='Needs clarification' for r in data['review']),
                    created_records=len(new), updated_therapies=len(updated), provider_writes=0, payment_writes=0)
    finally:
        db.rollback()
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(install(args.database, args.apply)))
