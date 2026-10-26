"""Add owner-approved per-SKU refill policies; never rewrite care/order snapshots."""
import argparse
import json
from pathlib import Path
import sqlite3
import time
from catalog_refill_policies import source_products, source_binding, proposed_policy
from refill_rules import SaveRefillRules, validate_included_policy

RUN_ID = 'owner-approved-wellness-refill-policies-v1'


def prepare(existing):
    result = {}
    for p in source_products():
        for sku in (p['sku'], p['sku'] + '-SUB'):
            master = existing.get(('master', sku)) or {}
            setup = master.get('product_setup') or {}
            expected_days = [i * p['supply_days_per_shipment'] for i in range(p['shipments_per_term'])]
            if (master.get('therapy_id') != p['therapy_id'] or master.get('treatment_id') != p['treatment_id']
                    or setup.get('term_months') != p['duration_months']
                    or setup.get('shipment_days') != expected_days
                    or setup.get('renewal_days') != (p['duration_months'] * 30 if sku.endswith('-SUB') else None)):
                raise ValueError('Master differs from approved source; reconcile refill rules: ' + sku)
            if ('refill_policy', sku) in existing:
                raise ValueError('Existing refill policy preserved; reconcile: ' + sku)
            policy = proposed_policy(p, sku)
            body = SaveRefillRules.model_validate({k: v for k, v in policy.items() if k not in ('sku', 'revision')} | {'expected_revision': 0})
            validate_included_policy(body, source_binding(sku), setup)
            result['refill_policy', sku] = policy
    return result


def install(path, apply=False):
    path = Path(path).resolve(strict=True)
    db = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=10)
    try:
        db.execute('BEGIN IMMEDIATE' if apply else 'BEGIN')
        existing = {(k, i): json.loads(v) for k, i, v in db.execute('SELECT kind,id,data FROM admin_config')}
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='admin_setup_runs'").fetchone():
            row = db.execute('SELECT details FROM admin_setup_runs WHERE id=?', (RUN_ID,)).fetchone()
            if row:
                if any(tuple(k) not in existing for k in json.loads(row[0])['created_records']):
                    raise ValueError('Incomplete refill import; reconcile without overwriting')
                return {'already_imported': True, 'created_records': 0}
        pending = prepare(existing)
        if apply:
            db.execute('CREATE TABLE IF NOT EXISTS admin_setup_runs(id TEXT PRIMARY KEY,created REAL NOT NULL,details TEXT NOT NULL)')
            for (kind, key), value in pending.items():
                db.execute('INSERT INTO admin_config VALUES(?,?,?)', (kind, key, json.dumps(value)))
            db.execute('INSERT INTO admin_setup_runs VALUES(?,?,?)', (RUN_ID, time.time(), json.dumps({
                'authorization': 'Owner requested per-therapy refill policies from source delivery and check-in rules',
                'created_records': [list(k) for k in pending], 'provider_writes': 0})))
            db.commit()
        return {'applied': apply, 'policies': len(pending), 'created_records': len(pending) if apply else 0,
                'included_refill_policies': sum(p['included_refills_enabled'] for p in pending.values()),
                'claim_window_days': 20, 'provider_writes': 0}
    finally:
        db.rollback()
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(install(args.database, args.apply)))
