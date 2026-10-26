"""Patient-owned replacement checkout. No card data; no optimistic cancellation.

Existing session APIs own authorization/capture. A durable journal binds the
receipt to this patient and source plan. Stop old renewals only after capture.
"""
import json
import secrets
import threading
from datetime import timedelta
from urllib.parse import urlsplit, parse_qs
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from .provider import ProviderError


class StartUpgrade(BaseModel):
    model_config = ConfigDict(extra='forbid')
    plan_id: str = Field(min_length=1, max_length=100)


class Upgrades:
    def __init__(self, service):
        self.s = service
        self.guard = threading.RLock()
        with service.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS member_upgrades(
                id TEXT PRIMARY KEY,site_id TEXT NOT NULL,patient_id TEXT NOT NULL,
                source_order_id TEXT NOT NULL,term_id TEXT NOT NULL,subscription_id TEXT NOT NULL,
                plan_id TEXT NOT NULL,sku TEXT NOT NULL,api_site TEXT NOT NULL,
                session_id TEXT,secret TEXT,status TEXT NOT NULL,new_order_id TEXT,created REAL NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS member_upgrade_once ON member_upgrades(site_id,patient_id,term_id)
                WHERE status!='abandoned';''')
            db.execute("UPDATE member_upgrades SET status='needs_review' WHERE status IN ('initializing','stopping')")

    def policy(self, row):
        raw, snap = json.loads(row['payload']), json.loads(row['snapshot'])
        result = {'eligible': False, 'opens_at': None, 'supply_ends_at': None,
                  'included_remaining': None, 'reason': 'Your supply schedule needs verification before changing plans.'}
        plan = self.s.care.ensure(row)
        if not plan or not snap.get('schedule_verified') or raw.get('payment_status') != 'paid':
            return result
        data = json.loads(plan['snapshot'])
        start = self.s.date(data.get('start_date'))
        coverage = data.get('coverage_days')
        setup = data.get('product_setup') or {}
        count = setup.get('shipment_count')
        if not start or type(coverage) is not int or coverage <= 0 or type(count) is not int or count < 1:
            return result
        end = start + timedelta(days=coverage)
        opens = max(start, end - timedelta(days=20))
        result.update(opens_at=opens.isoformat(), supply_ends_at=end.isoformat())
        tasks = self.s.care.tasks(row, plan)
        checkpoints = [t for t in tasks if t.get('refill_checkpoint')]
        claimed = sum((t.get('claim') or {}).get('status') == 'claimed' for t in checkpoints)
        remaining = max(0, count - 1 - claimed)
        result['included_remaining'] = remaining
        if remaining:
            result['reason'] = 'Use your remaining included refills before changing plans.'
            return result
        if any((t.get('claim') or {}).get('status') in ('pending','processing','uncertain','reconciliation_required') for t in checkpoints):
            result['reason'] = 'Your last refill is still being confirmed.'
            return result
        if self.s.date(self.s.care.simulation(row)['effective_date']) < opens:
            result['reason'] = 'You can choose your next plan from ' + opens.isoformat() + ', 20 days before your current supply ends.'
            return result
        # A later paid term supersedes this one; old cards must not offer a second upgrade.
        with self.s.db() as db:
            related = db.execute('SELECT snapshot FROM member_orders WHERE site_id=? AND customer_id=?', (row['site_id'], row['customer_id'])).fetchall()
        for other in related:
            value = json.loads(other['snapshot'])
            if (value.get('root_order_id') == snap.get('root_order_id') and value.get('product_id') == snap.get('product_id')
                    and (value.get('term_started_at') or '') > (snap.get('term_started_at') or '')):
                result['reason'] = 'A newer renewal already exists. Open your latest plan.'
                return result
        result.update(eligible=True, reason='Choose your next plan and pay securely here.')
        return result

    def existing(self, row, patient_id):
        term = str(json.loads(row['snapshot']).get('term_order_id') or row['order_id'])
        with self.s.db() as db:
            item = db.execute("SELECT * FROM member_upgrades WHERE site_id=? AND patient_id=? AND term_id=? AND status!='abandoned'", (row['site_id'], patient_id, term)).fetchone()
        return dict(item) if item else None

    def busy_subscription(self, site_id, subscription_id):
        with self.s.db() as db:
            row = db.execute("SELECT 1 FROM member_upgrades WHERE site_id=? AND subscription_id=? AND subscription_id!='' AND status!='abandoned'", (site_id, subscription_id)).fetchone()
        return bool(row)

    def read(self, site, key, patient):
        with self.s.db() as db:
            row = db.execute('SELECT * FROM member_upgrades WHERE id=? AND site_id=? AND patient_id=?', (key, site, patient['id'])).fetchone()
        if not row:
            raise HTTPException(404, 'Checkout not found')
        self.s.order_record(site, row['source_order_id'], patient)
        return dict(row)

    def update(self, key, **values):
        allowed = {'status', 'session_id', 'secret', 'new_order_id'}
        if not set(values) <= allowed: raise ValueError('Invalid update')
        with self.s.db() as db:
            db.execute('UPDATE member_upgrades SET '+','.join(k+'=?' for k in values)+' WHERE id=?', (*values.values(), key))

    def cipher(self):
        if not hasattr(self, '_cipher'):
            from .identity import StickyIdentity
            self._cipher = self.s.identity or StickyIdentity(self.s)
        return self._cipher

    def api(self, app):
        facade = getattr(app.state, 'site_api', None)
        if not facade or not hasattr(facade.state, 'session_operations'):
            raise HTTPException(503, 'On-page checkout is not configured for this site')
        return facade

    def latest(self, source):
        """Refresh explicit children only, never look up patients by email."""
        row = self.s.sync(source['site_id'], source['order_id'])
        self.s.sync_children(row)
        snap = json.loads(row['snapshot'])
        with self.s.db() as db:
            rows = db.execute('SELECT * FROM member_orders WHERE site_id=? AND customer_id=?', (row['site_id'], row['customer_id'])).fetchall()
        members = [dict(r) for r in rows if json.loads(r['snapshot']).get('term_order_id') == snap.get('term_order_id') and json.loads(r['snapshot']).get('product_id') == snap.get('product_id')]
        terminal = [r for r in members if not json.loads(r['payload']).get('child_ids')]
        if len(terminal) != 1:
            raise HTTPException(409, 'Your renewal history changed. Refresh your orders before changing plans.')
        return row, terminal[0]

    def start(self, app, site, order, patient, body, req):
        from demo.session_api import CreateSession
        with self.guard:
            source = self.s.order_record(site, order, patient)
            existing = self.existing(source, patient['id'])
            if existing:
                if existing['plan_id'] != body.plan_id:
                    raise HTTPException(409, 'Resume your existing checkout before selecting a different plan.')
                return {'id': existing['id'], 'status': existing['status']}
            source, last = self.latest(source)
            policy = self.policy(source)
            if not policy['eligible']: raise HTTPException(409, policy['reason'])
            line = json.loads(last['payload'])['products'][0]
            if line.get('billing_status') not in ('active','held','inactive'):
                raise HTTPException(409, 'Your subscription status needs confirmation')
            sub = str(line.get('subscription_id') or '') if line.get('billing_status') in ('active','held') else ''
            plans = self.s.store_catalog(site, source['therapy_id'])['plans']
            selected = next((p for p in plans if p['plan_id'] == body.plan_id), None)
            if not selected: raise HTTPException(404, 'Plan is not available for this treatment')
            facade = self.api(app)
            publication = next((p for p in facade.state.publications.values() if p.portal_site_id == site), None)
            if not publication: raise HTTPException(409, 'The site checkout publication is unavailable')
            key = 'upgrade_' + secrets.token_urlsafe(20)
            term = str(json.loads(source['snapshot']).get('term_order_id') or order)
            with self.s.db() as db:
                db.execute('BEGIN IMMEDIATE')
                if sub and (db.execute("SELECT 1 FROM member_renewal_quotes WHERE site_id=? AND subscription_id=? AND status IN ('processing','uncertain')", (site,sub)).fetchone()
                    or db.execute("SELECT 1 FROM member_actions WHERE site_id=? AND subscription_id=? AND status IN ('pending','uncertain')", (site,sub)).fetchone()):
                    raise HTTPException(409, 'An existing subscription change is still being confirmed')
                db.execute('INSERT INTO member_upgrades VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (key,site,patient['id'],order,term,sub,body.plan_id,selected['sku'],publication.site_id,None,None,'initializing',None,self.s.clock()))
            try:
                session = facade.state.session_operations['create'](publication.site_id, CreateSession(plan_id=selected['sku'].lower()), req)
                session_row = app.state.site_api_store.read(session.session_id)
                expected = parse_qs(urlsplit(selected['checkout_url']).query).get('option', [''])[0]
                if session_row['selection'] != expected:
                    raise HTTPException(409, 'The published plan changed. Please refresh your choices.')
                self.update(key, session_id=session.session_id, secret=self.cipher().encrypt(session.session_token), status='open')
            except Exception:
                self.update(key, status='abandoned')
                raise
            return {'id': key, 'status': 'open'}

    def invoke(self, app, saved, operation, req, body=None):
        from demo.session_api import QuoteBody, PaymentBody, CompleteBody, Empty
        if saved['status'] in ('needs_review','stopping','initializing','abandoned') or not saved['session_id']:
            raise HTTPException(409, 'This checkout needs review. Do not start another payment.')
        handlers = self.api(app).state.session_operations
        args = [saved['api_site'], saved['session_id']]
        models = {'quote': QuoteBody, 'payment': PaymentBody, 'complete': CompleteBody, 'resume': Empty}
        if operation in models:
            try: args.append(models[operation].model_validate(body or {}))
            except ValidationError: raise HTTPException(422, 'Check the checkout details and try again.') from None
        args.extend([req, HTTPAuthorizationCredentials(scheme='Bearer', credentials=self.cipher().decrypt(saved['secret']))])
        return handlers[operation](*args)

    def finish(self, app, saved, patient, result):
        if result.status != 'captured': return result.model_dump()
        session = app.state.site_api_store.read(saved['session_id'])
        receipt = self.s.store.read(session['attempt'])
        order, _ = self.s.receipt_order(receipt)
        raw = json.loads(order['payload'])
        if (order['site_id'] != saved['site_id'] or order['sku'] != saved['sku'] or raw['customer']['email'].strip().lower() != patient['email'].strip().lower()):
            self.update(saved['id'], status='needs_review')
            raise HTTPException(409, 'Your paid order needs account-linking review. Do not pay again.')
        with self.s.db() as db:
            grant = db.execute('SELECT patient_id FROM member_grants WHERE site_id=? AND order_id=?', (saved['site_id'], order['order_id'])).fetchone()
            if grant and grant['patient_id'] != patient['id']: raise HTTPException(409, 'Order ownership needs review')
            db.execute('INSERT OR IGNORE INTO member_grants VALUES(?,?,?,?,?)', (saved['site_id'],order['order_id'],patient['id'],self.s.clock(),'portal_checkout'))
        if saved['status'] == 'complete': return {'status': 'captured', 'order_id': order['order_id'], 'replacement_complete': True}
        self.update(saved['id'], new_order_id=order['order_id'])
        if saved['subscription_id']:
            # Reserve before the provider write. A crash/timeout can never replay it.
            self.update(saved['id'], status='stopping')
            try:
                source = self.s.order_record(saved['site_id'], saved['source_order_id'], patient)
                source, last = self.latest(source)
                if not self.policy(source)['eligible']: raise HTTPException(409, 'Source plan changed')
                self.s.provider.subscription_action(last['order_id'], saved['subscription_id'], 'pause', expected_campaign=self.s.site(saved['site_id'])[0]['campaign_id'], expected_customer_id=source['customer_id'])
                self.s.sync(saved['site_id'], last['order_id'])
            except Exception:
                self.update(saved['id'], status='needs_review')
                return {'status': 'captured', 'order_id': order['order_id'], 'replacement_complete': False,
                        'message': 'Your new order is paid. We need to confirm that the previous subscription has stopped. Do not place another order.'}
        self.update(saved['id'], status='complete')
        return {'status': 'captured', 'order_id': order['order_id'], 'replacement_complete': True}

    def attach(self, app, router, auth):
        @router.get('/orders/{order_id}/upgrade')
        def eligibility(site_id: str, order_id: str, patient=Depends(auth)):
            source = self.s.order_record(site_id, order_id, patient)
            result = self.policy(source)
            existing = self.existing(source, patient['id'])
            if existing:
                result.update(eligible=False, checkout={'id': existing['id'], 'status': existing['status'], 'order_id': existing['new_order_id']})
            return result

        @router.post('/orders/{order_id}/upgrade')
        def start(site_id: str, order_id: str, body: StartUpgrade, req: Request, patient=Depends(auth)):
            return self.start(app, site_id, order_id, patient, body, req)

        @router.get('/upgrades/{upgrade_id}/{operation}')
        def read(site_id: str, upgrade_id: str, operation: str, req: Request, patient=Depends(auth)):
            if operation not in ('configuration','status'): raise HTTPException(404)
            with self.guard:
                saved = self.read(site_id, upgrade_id, patient)
                if operation == 'status' and saved['status'] in ('needs_review','complete'):
                    return {'status': saved['status'], 'order_id': saved['new_order_id']}
                result = self.invoke(app, saved, operation, req)
                return self.finish(app, saved, patient, result) if operation == 'status' else result

        @router.post('/upgrades/{upgrade_id}/{operation}')
        def write(site_id: str, upgrade_id: str, operation: str, body: dict, req: Request, patient=Depends(auth)):
            if operation not in ('quote','payment','complete','resume','abandon'): raise HTTPException(404)
            with self.guard:
                saved = self.read(site_id, upgrade_id, patient)
                if operation == 'abandon':
                    session = app.state.site_api_store.read(saved['session_id'])
                    if saved['status'] != 'open' or session['phase'] not in ('new','quoted') or session['held'] or session['busy']:
                        raise HTTPException(409, 'This payment has started. Check its status before changing plans.')
                    self.update(saved['id'], status='abandoned', secret=None)
                    return {'status': 'abandoned'}
                if operation == 'quote' and (body.get('contact') or {}).get('email','').strip().lower() != patient['email'].strip().lower():
                    raise HTTPException(422, 'Use the email address of your signed-in account')
                if operation == 'payment' and saved['subscription_id'] and body.get('accept_terms') is not True:
                    raise HTTPException(422, 'Confirm replacement of your existing subscription before payment.')
                if operation in ('quote','payment'):
                    source = self.s.order_record(site_id, saved['source_order_id'], patient)
                    if operation == 'payment': source, _ = self.latest(source)
                    policy = self.policy(source)
                    if not policy['eligible']: raise HTTPException(409, policy['reason'])
                result = self.invoke(app, saved, operation, req, body)
                return self.finish(app, saved, patient, result) if operation == 'complete' else result
