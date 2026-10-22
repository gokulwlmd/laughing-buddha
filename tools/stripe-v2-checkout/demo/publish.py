"""Publish only the owner's approved campaign-422 payment-test demo copy.

Run inside the existing checkout machine. No processor writes, owner/session
fabrication, private invitations, or existing record edits. Public API children are public too; older cookie-
scoped demo children and their payment attempts are not modified. Existing attempts
and links are retained. The caller must explicitly authorize public access.
"""
from copy import deepcopy
import hashlib
import json
import time
from plans import choice_id

LEGACY_DEMO_ID = 'site-api-demo-weight-loss'
DEMO_ID = 'site-api-public-weight-loss'


def publication(admin):
    candidates = [p for p in admin.records('plan_checkout') if p.get('campaign_id') == 422
        and p.get('therapy_id') == 'weight-loss' and p.get('payment_test_only')
        and p.get('enabled') and p['id'] not in (DEMO_ID, LEGACY_DEMO_ID)]
    if len(candidates) != 1:
        raise RuntimeError('Expected one approved weight-loss payment-test checkout')
    source = candidates[0]
    if len(source['entries']) != 16:
        raise RuntimeError('Expected the sixteen approved payment-test plans')
    plan = deepcopy(source)
    plan.update(id=DEMO_ID, title='API demo · Weight Loss', visibility='public', revision=1)
    children = []
    for entry in plan['entries']:
        old = admin.get('link', choice_id(source['id'], entry['sku'], entry.get('purchase_option_id', '')))
        if not old or not old.get('enabled') or old['options'] != entry['options']:
            raise RuntimeError('Source checkout mapping needs review')
        child = deepcopy(old)
        child.update(id=choice_id(DEMO_ID, entry['sku'], entry.get('purchase_option_id', '')),
            plan_checkout_id=DEMO_ID, revision=1, visibility='public')
        children.append(child)
    return [('plan_checkout', plan)] + [('link', c) for c in children]


def publish(admin):
    records = publication(admin)
    # Verify current upstream availability before any local configuration write.
    source = next(p for p in admin.records('plan_checkout') if p.get('campaign_id') == 422
        and p.get('therapy_id') == 'weight-loss' and p['id'] not in (DEMO_ID, LEGACY_DEMO_ID) and p.get('payment_test_only') and p.get('enabled'))
    catalog = admin.plan_options(*admin.plan_record(source['id']))
    if len(catalog['entries']) != 16 or not all(e['available'] for e in catalog['entries']):
        raise RuntimeError('A source payment-test choice is unavailable')
    # Strict idempotency: never replace an existing demo or silently broaden it.
    with admin.store.db() as db:
        for kind, record in records:
            row = db.execute('SELECT data FROM admin_config WHERE kind=? AND id=?', (kind, record['id'])).fetchone()
            if row and json.loads(row[0]) != record:
                raise RuntimeError('Existing demo differs; explicit review required')
        missing = [(kind, record) for kind, record in records if not db.execute(
            'SELECT 1 FROM admin_config WHERE kind=? AND id=?', (kind, record['id'])).fetchone()]
        if missing and len(missing) != len(records):
            raise RuntimeError('Partial demo publication needs reconciliation')
        if missing:
            db.execute('CREATE TABLE IF NOT EXISTS public_demo_publications(id TEXT PRIMARY KEY,created REAL NOT NULL,record_count INTEGER NOT NULL,fingerprint TEXT NOT NULL)')
            db.executemany('INSERT INTO admin_config(kind,id,data) VALUES(?,?,?)',
                [(kind, r['id'], json.dumps(r)) for kind, r in missing])
            db.execute('INSERT INTO public_demo_publications VALUES(?,?,?,?)', (DEMO_ID,time.time(),len(records),
                hashlib.sha256(json.dumps(records,sort_keys=True).encode()).hexdigest()))
    return {'id':DEMO_ID, 'published_records':len(missing), 'plans':16, 'processor_writes':0}
