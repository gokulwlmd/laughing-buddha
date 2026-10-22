"""Operator recovery for the verified legacy first-product weight-default failure.

This resumes an already approved site plan. It cannot retry an uncertain write,
alter its payloads, approve a draft, or create a replacement for a recorded ID.
"""
import argparse
import hashlib
import json
import sqlite3
import time
from pathlib import Path

from master import fingerprint, model_rows, product_contract, product_contract_matches
from catalog import money, resolve


def recover(admin, review_id, apply=False):
    with admin.store.db() as db:
        row = db.execute('SELECT kind,status,data,result,before_hash FROM admin_reviews WHERE id=?', (review_id,)).fetchone()
    if not row or row[0] != 'site' or row[1] != 'reconcile':
        raise ValueError('Only a held, previously approved site setup can be inspected')
    plan, result = json.loads(row[2]), json.loads(row[3] or '{}')
    operations = plan['operations']
    first = operations[0]
    created = result.get('created', {})
    if ('operation_index' in result or first['method'] != 'POST' or first['path'] != '/api/v2/products'
            or set(created) != {first.get('save')} or len(operations) < 2
            or operations[1]['path'] != '/api/v2/offers'):
        raise ValueError('This is not the verified legacy first-product failure; inspect the journal instead')
    expected = first['verify']
    product_id = created[first['save']]
    actual = admin.api.detail(f'/api/v2/products/{product_id}')
    contract = product_contract(actual)
    if (expected['kind'] != 'product' or actual.get('sku') != expected['sku']
            or money(actual.get('price')) != money(expected['price'])
            or expected['contract'] == contract
            or not product_contract_matches(expected['contract'], contract)):
        raise ValueError('Recorded product does not have only the verified harmless default mismatch')
    if admin.local_fingerprint() != row[4]:
        raise ValueError('Local configuration changed after approval; recovery needs a fresh comparison')
    campaign_id = plan['data']['campaign_id']
    if type(campaign_id) is not int:
        raise ValueError('This recovery is restricted to an existing approved campaign')
    with admin.store.db() as db:
        if db.execute("SELECT 1 FROM checkouts WHERE campaign=? AND status NOT IN ('new','captured') LIMIT 1", (campaign_id,)).fetchone():
            raise ValueError('The campaign has an open payment')
    for guard in plan['guards']:
        if 'models' in guard:
            current = fingerprint(model_rows(admin.api))
        elif 'gateway_currency' in guard:
            gid = guard['gateway_currency']
            g = admin.api.detail(f'/api/v2/providers/payment/profiles/{gid}')
            raw = g.get('currency')
            currency = str((raw.get('code') or raw.get('name','')) if isinstance(raw, dict) else raw or '').upper()
            current = fingerprint({'id':gid,'account_id':g.get('account_id'),'currency':currency})
        elif 'catalog' in guard:
            current = resolve(admin.api, *guard['catalog'])['fingerprint']
        else:
            obj = admin.api.detail(guard['path'])
            current = fingerprint({k:obj.get(k) for k in guard['keys']} if guard['keys'] else obj)
        if current != guard['hash']:
            raise ValueError('Sticky configuration changed after approval; recovery stopped')
    summary = {'campaign_id':campaign_id,'reused_product_id':product_id,
               'remaining_operations':len(operations)-1,'applied':False,'payment_requests':0}
    if not apply:
        return summary
    backup_dir = admin.cfg.state_dir/'reconciliation-backups'
    backup_dir.mkdir(mode=0o700, exist_ok=True)
    tag = hashlib.sha256(review_id.encode()).hexdigest()[:16]
    backup = backup_dir/f'site-{tag}.sqlite3'
    if backup.exists():
        raise ValueError('A recovery backup already exists; inspect the earlier recovery before continuing')
    with admin.store.db() as db, sqlite3.connect(backup) as dest:
        db.backup(dest)
    backup.chmod(0o600)
    with admin.store.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS admin_recoveries(id TEXT PRIMARY KEY,review_id TEXT NOT NULL,reason TEXT NOT NULL,started REAL NOT NULL,result TEXT)')
        changed = db.execute("UPDATE admin_reviews SET status='applying' WHERE id=? AND status='reconcile' AND data=? AND result=?", (review_id,row[2],row[3])).rowcount
        if changed != 1:
            raise ValueError('The held review changed during inspection')
        db.execute('INSERT INTO admin_recoveries VALUES(?,?,?,?,NULL)', (tag,review_id,'Verified non-shippable weight defaults; reuse first product',time.time()))
    try:
        applied = admin.execute_plan(review_id, 'site', plan, completed=created, start_index=1)
    except Exception:
        with admin.store.db() as db:
            db.execute('UPDATE admin_recoveries SET result=? WHERE id=?', (json.dumps({'status':'held','automatic_retry':False}),tag))
        raise
    with admin.store.db() as db:
        db.execute('UPDATE admin_recoveries SET result=? WHERE id=?', (json.dumps({'status':'applied','created':applied['created']}),tag))
    return dict(summary, applied=True, result=applied)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('review_id')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    from app import app
    print(json.dumps(recover(app.state.admin, args.review_id, apply=args.apply)))


if __name__ == '__main__':
    main()
