"""Patient claims consume native prepaid cycles; never create a separate sale.

One durable write intent per paid term/cycle. Uncertain provider writes are
reconciled by reads only and never retried automatically.
"""
from datetime import timedelta
from decimal import Decimal
import json
import secrets
from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from external_fulfillment import fortifyhp_order_scope
from .provider import ProviderError, ProviderRejected, ProviderUncertain
from .care import stamp


class ClaimRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    client_request_id: str = Field(min_length=8, max_length=100, pattern=r'^[A-Za-z0-9_-]+$')


class ClaimsManager:
    def __init__(self, service):
        self.s = service
        with service.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS member_refill_claims(
                    id TEXT PRIMARY KEY,plan_id TEXT NOT NULL,site_id TEXT NOT NULL,patient_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,target_cycle INTEGER NOT NULL,parent_order_id TEXT NOT NULL,
                    child_order_id TEXT,status TEXT NOT NULL,client_request_id TEXT NOT NULL,
                    created REAL NOT NULL,updated REAL NOT NULL,simulated INTEGER NOT NULL,error TEXT NOT NULL,
                    UNIQUE(plan_id,target_cycle),UNIQUE(site_id,patient_id,client_request_id));
            ''')

    def rows(self, row, plan):
        with self.s.db() as db:
            records = db.execute('SELECT o.* FROM member_orders o JOIN member_grants g ON g.site_id=o.site_id AND g.order_id=o.order_id WHERE o.site_id=? AND g.patient_id=? AND o.customer_id=?',
                (row['site_id'], plan['patient_id'], row['customer_id'])).fetchall()
        result = []
        for record in records:
            record = dict(record)
            snap, raw = json.loads(record['snapshot']), json.loads(record['payload'])
            line = raw['products'][0]
            if (snap.get('root_order_id') == plan['root_order_id'] and snap.get('term_order_id') == plan['term_order_id']
                    and str(snap['product_id']) == str(plan['product_id']) and record['sku'] == plan['sku']
                    and line.get('prepaid') and line.get('subscription_id')):
                result.append(record)
        return result

    def cycle_row(self, row, plan, cycle):
        matches = []
        for record in self.rows(row, plan):
            raw = json.loads(record['payload']); line = raw['products'][0]
            if line['prepaid']['current_cycle'] == cycle and raw['payment_status'] == 'paid':
                if cycle > 1 and Decimal(raw['total']) != 0:
                    continue
                matches.append(record)
        return matches[0] if len(matches) == 1 else None

    def recorded(self, plan_id, target):
        with self.s.db() as db:
            row = db.execute('SELECT * FROM member_refill_claims WHERE plan_id=? AND target_cycle=?', (plan_id, target)).fetchone()
        return dict(row) if row else None

    def task_state(self, row, plan, task):
        rule = self.s.rule(row['sku'], row['site_id'])
        result = {'available': False, 'status': 'unavailable', 'order_id': None, 'claim_id': None,
                  'created_at': None, 'opens_at': None, 'amount': '0.00', 'reason': '', 'simulated': False}
        if not rule.get('included_refills_enabled') or task['kind'] == 'initial':
            return result
        data = json.loads(plan['snapshot']); setup = data['product_setup']
        interval, count = setup.get('shipment_interval_days'), setup.get('shipment_count')
        if not interval or not count or task['day_offset'] % interval:
            return result | {'reason': 'Your included refill schedule needs review. Please contact support.'}
        target = task['day_offset'] // interval + 1
        if not 2 <= target <= count:
            return result
        start = self.s.date(data['start_date'])
        opens = max(start + timedelta(days=int(rule.get('minimum_days', 0))),
                    start + timedelta(days=task['day_offset'] - int(rule.get('claim_window_days', 20))))
        result['opens_at'] = opens.isoformat()
        saved = self.recorded(plan['id'], target)
        if saved and saved['status'] in ('processing', 'uncertain'):
            return result | {'status': saved['status'], 'claim_id': saved['id'],
                'reason': 'We are confirming your refill order. Please do not submit another claim.'}
        child = self.cycle_row(row, plan, target)
        if child:
            if not saved or saved['status'] != 'claimed' or saved['child_order_id'] != child['order_id']:
                return result | {'status': 'uncertain',
                    'reason': 'We found a refill order and need to confirm its schedule. Check its status.'}
            return result | {'status': 'claimed', 'order_id': child['order_id'],
                'claim_id': saved['id'], 'created_at': stamp(saved['created']),
                'simulated': bool(saved['simulated']),
                'reason': 'Your included refill order is placed.' + (' Complete its check-in.' if task['required'] else ' No refill check-in is required.')}
        if saved:
            return result | {'status': 'uncertain', 'claim_id': saved['id'],
                'reason': 'We need to confirm the existing refill order. Please contact support.'}
        if not rule.get('enabled'):
            return result | {'reason': 'Refill claims are currently unavailable. Please contact support.'}
        parent = self.cycle_row(row, plan, target - 1)
        if not parent:
            return result | {'status': 'locked', 'reason': 'Claim your earlier included refill first.'}
        raw = json.loads(parent['payload']); line = raw['products'][0]
        if raw.get('child_ids'):
            return result | {'reason': 'Refresh your orders to confirm the next included refill.'}
        if line.get('billing_status') != 'active':
            return result | {'reason': 'Your plan is paused or inactive. Review your subscription first.'}
        payment_test_only = bool(raw.get('test_order') or json.loads(parent['snapshot']).get('payment_test_only'))
        if payment_test_only and not rule.get('test_requests_enabled'):
            return result | {'reason': 'Claims are not enabled for this test order.'}
        external = (line.get('is_shippable') is True and raw.get('test_order') is False
                    and fortifyhp_order_scope(raw.get('campaign_id'), raw.get('gateway_id'), line.get('sku')))
        if line.get('is_shippable') is not False and not external:
            return result | {'reason': 'Please contact support to arrange this refill.'}
        today = self.s.date(self.s.care.simulation(row)['effective_date'])
        if today >= start + timedelta(days=data['coverage_days']):
            return result | {'reason': 'This prepaid term has ended. Choose your next plan.'}
        if today < opens:
            return result | {'status': 'locked', 'reason': 'Your included refill opens on ' + opens.isoformat() + '.'}
        with self.s.db() as db:
            initial = db.execute("SELECT status,simulated FROM member_care_intakes WHERE plan_id=? AND task_id='initial'", (plan['id'],)).fetchone()
            earlier = db.execute('SELECT task_id,status,simulated FROM member_claim_intakes WHERE plan_id=?', (plan['id'],)).fetchall()
        first_form_kind = data.get('first_form_kind', 'initial')
        if first_form_kind == 'none':
            # No new questionnaire on this renewal; the original required intake
            # still has to exist. A renewal payment is not an intake submission.
            with self.s.db() as db:
                initial = db.execute('''SELECT i.status,i.simulated FROM member_care_intakes i
                    JOIN member_care_plans p ON p.id=i.plan_id
                    WHERE p.site_id=? AND p.patient_id=? AND p.root_order_id=?
                    AND p.term_order_id=? AND p.product_id=? AND i.task_id='initial' ''',
                    (plan['site_id'], plan['patient_id'], plan['root_order_id'], plan['root_order_id'], plan['product_id'])).fetchone()
        if not initial or initial['status'] != 'submitted':
            return result | {'status': 'locked', 'reason': 'Complete your refill check-in first.' if first_form_kind == 'checkin' else 'Complete your initial health intake first.'}
        prior_days = [day for day in data['rule'].get('check_in_days', []) if day < task['day_offset']]
        complete = {r['task_id'] for r in earlier if r['status'] == 'submitted'}
        if data['rule'].get('check_in_required', True) and any('checkin-' + str(day) not in complete for day in prior_days):
            return result | {'status': 'locked', 'reason': 'Complete the check-in for your previous refill first.'}
        if not self.s.care.simulation(row)['available'] and ((initial and initial['simulated']) or any(r['simulated'] for r in earlier)):
            return result | {'reason': 'Test answers cannot qualify this refill. Please contact your care team.'}
        return result | {'available': True, 'status': 'available', 'reason': 'Included in your plan. $0 due today.'}

    def arguments(self, row, plan, parent, target):
        data, snap = json.loads(plan['snapshot']), json.loads(row['snapshot'])
        raw = json.loads(parent['payload']); line = raw['products'][0]
        setup = data['product_setup']
        return dict(expected_campaign=self.s.site(row['site_id'])[0]['campaign_id'],
            expected_customer_id=row['customer_id'], expected_subscription_id=line['subscription_id'],
            expected_product_id=plan['product_id'], expected_offer_id=line.get('offer_id'),
            expected_billing_model_id=line.get('billing_model_id'), term_order_id=plan['term_order_id'],
            term_started_at=snap['term_started_at'], shipment_interval_days=setup['shipment_interval_days'],
            shipment_count=setup['shipment_count'], target_cycle=target)

    def finish(self, claim, child):
        # Refresh the recorded parent and import only its verified native chain;
        # never grant an arbitrary ID returned by a provider write.
        self.s.sync(claim['site_id'], claim['parent_order_id'])
        child_row = self.s.order_record(claim['site_id'], child['id'])
        if self.s.care.grant(child_row) != claim['patient_id']:
            raise ProviderUncertain('The refill order needs account reconciliation')
        with self.s.db() as db:
            db.execute("UPDATE member_refill_claims SET status='claimed',child_order_id=?,updated=?,error='' WHERE id=?",
                (child['id'], self.s.clock(), claim['id']))

    def claim(self, site_id, order_id, task_id, body, patient):
        row = self.s.order_record(site_id, order_id, patient)
        self.s.sync(site_id, order_id)
        row = self.s.order_record(site_id, order_id, patient)
        ctx = self.s.care.claim_context(row, task_id)
        plan, task, target = ctx['plan'], ctx['task'], ctx['target_cycle']
        with self.s.db() as db:
            reused = db.execute('SELECT * FROM member_refill_claims WHERE site_id=? AND patient_id=? AND client_request_id=?', (site_id, patient['id'], body.client_request_id)).fetchone()
        if reused and (reused['plan_id'] != plan['id'] or reused['task_id'] != task_id):
            raise HTTPException(409, 'This request ID already belongs to another refill')
        saved = self.recorded(plan['id'], target)
        if saved:
            if saved['status'] != 'claimed':
                parent = self.s.order_record(site_id, saved['parent_order_id'], patient)
                try:
                    child = self.s.provider.reconcile_included_cycle(parent['order_id'], **self.arguments(row, plan, parent, target))
                    if child:
                        self.finish(saved, child)
                except (ProviderError, HTTPException):
                    pass
            result = self.task_state(row, plan, task)
            if result['status'] != 'claimed':
                raise HTTPException(409, 'Your existing refill claim needs confirmation. It will not be submitted again.')
            return {'claim': result, 'care_plan': self.s.care.public(row)}
        state = self.task_state(row, plan, task)
        if state['status'] == 'claimed':
            return {'claim': state, 'care_plan': self.s.care.public(row)}
        existing_child = self.cycle_row(row, plan, target)
        if existing_child:
            # The scheduler may already have created this cycle. Local import
            # alone is not proof of its exact paid term and anchored schedule.
            # Adopt only after the same provider verification, with no writes
            # to Sticky and no second force-bill call.
            parent = self.cycle_row(row, plan, target - 1)
            if not parent:
                raise HTTPException(409, 'The existing refill order needs confirmation')
            try:
                verified = self.s.provider.reconcile_included_cycle(parent['order_id'],
                    child_order_id=existing_child['order_id'], **self.arguments(row, plan, parent, target))
            except ProviderError:
                verified = None
            if not verified:
                raise HTTPException(409, 'The existing refill order needs confirmation')
            with self.s.db() as db:
                db.execute('BEGIN IMMEDIATE')
                if not db.execute('SELECT 1 FROM member_refill_claims WHERE plan_id=? AND target_cycle=?', (plan['id'], target)).fetchone():
                    if db.execute('SELECT 1 FROM member_refill_claims WHERE site_id=? AND patient_id=? AND client_request_id=?', (site_id, patient['id'], body.client_request_id)).fetchone():
                        raise HTTPException(409, 'This request ID already belongs to another refill')
                    now = self.s.clock()
                    db.execute('INSERT INTO member_refill_claims VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        ('claim_' + secrets.token_urlsafe(18), plan['id'], site_id, patient['id'], task_id, target,
                         parent['order_id'], verified['id'], 'claimed', body.client_request_id,
                         now, now, int(self.s.care.simulation(row)['enabled']), ''))
            return {'claim': self.task_state(row, plan, task), 'care_plan': self.s.care.public(row)}
        if not state['available']:
            raise HTTPException(409, state['reason'])
        parent = self.cycle_row(row, plan, target - 1)
        kwargs = self.arguments(row, plan, parent, target)
        try:
            self.s.provider.included_cycle_capability(parent['order_id'], **kwargs)
        except ProviderError as exc:
            raise HTTPException(409, str(exc)) from None
        with self.s.db() as db:
            db.execute('BEGIN IMMEDIATE')
            # Competing requests may have completed the provider preflight;
            # only one can reserve this paid term/cycle before any write.
            if db.execute('SELECT 1 FROM member_refill_claims WHERE plan_id=? AND target_cycle=?', (plan['id'], target)).fetchone():
                raise HTTPException(409, 'This refill claim is already being processed. Refresh your orders.')
            if db.execute('SELECT 1 FROM member_refill_claims WHERE site_id=? AND patient_id=? AND client_request_id=?', (site_id, patient['id'], body.client_request_id)).fetchone():
                raise HTTPException(409, 'This request ID already belongs to another refill')
            # Provider preflight can be slow. Reserve only while the current
            # local policy, membership and required answers still permit it.
            # BEGIN IMMEDIATE prevents a concurrent local policy change from
            # being committed between this recheck and the durable intent.
            current_row = self.s.order_record(site_id, order_id, patient)
            current_state = self.task_state(current_row, plan, task)
            current_parent = self.cycle_row(current_row, plan, target - 1)
            if not current_state['available']:
                raise HTTPException(409, current_state['reason'])
            if not current_parent or current_parent['order_id'] != parent['order_id']:
                raise HTTPException(409, 'Your scheduled order changed. Refresh before claiming this refill.')
            claim_id, now = 'claim_' + secrets.token_urlsafe(18), self.s.clock()
            db.execute('INSERT INTO member_refill_claims VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (claim_id, plan['id'], site_id, patient['id'], task_id, target, parent['order_id'], None,
                 'processing', body.client_request_id, now, now, int(self.s.care.simulation(row)['enabled']), ''))
        claim = self.recorded(plan['id'], target)
        try:
            child = self.s.provider.advance_included_cycle(parent['order_id'], **kwargs)
            self.finish(claim, child)
        except (ProviderError, HTTPException):
            with self.s.db() as db:
                db.execute("UPDATE member_refill_claims SET status='uncertain',updated=?,error='provider_confirmation_required' WHERE id=?", (self.s.clock(), claim_id))
            raise HTTPException(409, 'We are confirming your refill order. Please do not submit another claim.') from None
        row = self.s.order_record(site_id, order_id, patient)
        return {'claim': self.task_state(row, plan, task), 'care_plan': self.s.care.public(row)}

    def attach(self, router, auth):
        @router.post('/orders/{order_id}/care-tasks/{task_id}/claim')
        def claim(site_id: str, order_id: str, task_id: str, body: ClaimRequest, patient=Depends(auth)):
            return self.claim(site_id, order_id, task_id, body, patient)
