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
from demo.registry import SitePublication

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


def site_publication(admin, configuration):
    """Prepare only reviewed client choices, without editing source records.

    The caller supplies the deployment allowlist after provisioning/review.
    Current campaign/brand membership, payment availability and exact selections
    are checked again here. This function performs no writes.
    """
    site = SitePublication.model_validate(configuration)
    records = []
    for therapy in site.therapies:
        source,brand,source_therapy = admin.plan_record(therapy.source_plan_id)
        if (source.get('campaign_id') != site.campaign_id or source.get('brand_id') != site.brand_id
                or source.get('therapy_id') != therapy.therapy_id or not source.get('enabled')
                or source.get('payment_test_only') or brand.get('id') != site.brand_id):
            raise RuntimeError('Source checkout does not match the approved client')
        catalog = admin.plan_options(source,brand,source_therapy)
        if catalog.get('paymentTestOnly') is not False:
            raise RuntimeError('Payment-test catalogs cannot be published as client products')
        entries,children = [],[]
        for approved in therapy.plans:
            matches = [entry for entry in source['entries'] if entry.get('sku') == approved.sku
                and entry.get('purchase_option_id','') == approved.purchase_option_id]
            if len(matches) != 1 or matches[0].get('options') != [approved.selection]:
                raise RuntimeError('Source plan mapping needs review')
            visible = [entry for entry in catalog['entries'] if entry.get('sku') == approved.sku
                and entry.get('purchaseOptionId','') == approved.purchase_option_id]
            if (len(visible) != 1 or not visible[0].get('available')
                    or len(visible[0].get('options',[])) != 1
                    or visible[0]['options'][0].get('key') != approved.selection
                    or visible[0]['options'][0].get('blockedReason')):
                raise RuntimeError('An approved client plan is unavailable')
            old = admin.get('link',choice_id(source['id'],approved.sku,approved.purchase_option_id))
            if (not old or not old.get('enabled') or old.get('options') != [approved.selection]
                    or old.get('campaign_id') != site.campaign_id or old.get('brand_id') != site.brand_id
                    or old.get('payment_test_only') or old.get('plan_checkout_id') != source['id']):
                raise RuntimeError('Source child does not match the approved client')
            child = deepcopy(old)
            child.update(id=choice_id(therapy.published_plan_id,approved.sku,approved.purchase_option_id),
                plan_checkout_id=therapy.published_plan_id,visibility='public',revision=1)
            entries.append(deepcopy(matches[0]));children.append(child)
        plan = deepcopy(source)
        plan.update(id=therapy.published_plan_id,title=site.site_name+' · '+therapy.name,
            visibility='public',revision=1,entries=entries,payment_test_only=False)
        selected_options = {p.purchase_option_id for p in therapy.plans}
        plan['purchase_options'] = [p for p in plan.get('purchase_options',[]) if p['id'] in selected_options]
        records.extend([('plan_checkout',plan),*[('link',c) for c in children]])
    return records


def publish_site(admin, configuration):
    """Atomically add a verified site's public copies; never replace old records."""
    site = SitePublication.model_validate(configuration)
    records = site_publication(admin,site)
    # Validate the external API's public contract before committing any copies.
    # This catches unsupported currencies, renewal/ship schedules and duplicates.
    from demo.public import map_site_catalog
    catalogs = {}
    for therapy in site.therapies:
        original = admin.plan_options(*admin.plan_record(therapy.source_plan_id))
        catalogs[therapy.published_plan_id] = dict(original,id=therapy.published_plan_id)
    map_site_catalog(site,catalogs.__getitem__)
    fingerprint = hashlib.sha256(json.dumps(records,sort_keys=True).encode()).hexdigest()
    with admin.store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        for kind,record in records:
            row = db.execute('SELECT data FROM admin_config WHERE kind=? AND id=?',(kind,record['id'])).fetchone()
            if row and json.loads(row[0]) != record:
                raise RuntimeError('Existing client publication differs; explicit review required')
        missing = [(kind,record) for kind,record in records if not db.execute(
            'SELECT 1 FROM admin_config WHERE kind=? AND id=?',(kind,record['id'])).fetchone()]
        if missing and len(missing) != len(records):
            raise RuntimeError('Partial client publication needs reconciliation')
        if missing:
            db.execute('CREATE TABLE IF NOT EXISTS public_site_publications(id TEXT PRIMARY KEY,created REAL NOT NULL,record_count INTEGER NOT NULL,fingerprint TEXT NOT NULL)')
            db.executemany('INSERT INTO admin_config(kind,id,data) VALUES(?,?,?)',
                [(kind,record['id'],json.dumps(record)) for kind,record in missing])
            db.execute('INSERT INTO public_site_publications VALUES(?,?,?,?)',
                (site.site_id,time.time(),len(records),fingerprint))
    return {'site_id':site.site_id,'campaign_id':site.campaign_id,'published_records':len(missing),
        'plans':sum(len(t.plans) for t in site.therapies),'processor_writes':0}
