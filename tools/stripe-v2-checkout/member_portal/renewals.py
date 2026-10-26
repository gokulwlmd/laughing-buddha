"""Confirmed early renewals of one existing standard subscription.

Quote with recurring_total/calculate; reserve once before order_force_bill.
Never create a separate sale, retry an uncertain charge, or advance a prepaid
included cycle through this path. All provider writes require patient consent.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import secrets

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from .provider import ProviderError, ProviderRejected, ProviderUncertain, amount, flag, identifier, billing_model_terms


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def fingerprint(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


class RenewConsent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    quote_id: str = Field(min_length=16, max_length=100)
    confirmed: bool


class RenewalProvider:
    def __init__(self, provider, clock):
        self.p, self.clock = provider, clock

    def today(self):
        return datetime.fromtimestamp(self.clock(), timezone.utc).date()

    def quote(self, order_id, subscription_id, **scope):
        source = self.p.read_order(order_id, **scope)
        if source['payment_status'] != 'paid' or len(source['products']) != 1 or source['child_ids']:
            raise ProviderRejected('Refresh your orders before requesting the next refill.')
        line = source['products'][0]
        if (line['subscription_id'] != subscription_id or line['billing_status'] != 'active'
                or line['prepaid'] or line.get('in_trial') is not False or line['quantity'] != 1 or line['stop_after_next_cycle'] is not False):
            raise ProviderRejected('This plan cannot be renewed early here. Manage your subscription or contact support.')
        scheduled = line['next_billing_date']
        if not scheduled or scheduled <= (self.today() + timedelta(days=1)).isoformat():
            raise ProviderRejected('Your renewal is already due soon. Please let the scheduled payment complete.')
        if source['currency'] != 'USD' or not source['gateway_id']:
            raise ProviderRejected('The payment currency and gateway need verification.')
        paths = {'subscription': '/api/v2/subscriptions/' + subscription_id,
                 'gateway': '/api/v2/providers/payment/profiles/' + source['gateway_id']}
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {k: pool.submit(self.p._call_read, 'GET', path) for k, path in paths.items()}
            pricing = pool.submit(self.p._call_read, 'POST', '/api/v2/recurring_total/calculate',
                {'order_id': int(source['id']), 'recurring_date': scheduled, 'calculate_tax': True, 'calculate_shipping': True})
            data = {k: f.result() for k, f in futures.items()}
            calculated = pricing.result()
        for result in [*data.values(), calculated]:
            if result.get('status') != 'SUCCESS' or not isinstance(result.get('data'), dict):
                raise ProviderRejected('The renewal price could not be verified. Please try again later.')
        sub, gateway = data['subscription']['data'], data['gateway']['data']
        model = sub.get('billing_model') or {}
        mid, days = billing_model_terms({'billing_model': model})
        if (sub.get('id') != subscription_id or sub.get('status') != 'active'
                or flag(sub.get('is_recurring')) is not True or sub.get('recur_at') != scheduled
                or mid != line['billing_model_id'] or days not in (30, 90)
                or model.get('expire_cycles') not in (None, 0, '0') or model.get('buffer_days') not in (None, 0, '0')
                or flag(model.get('is_archived')) is True or flag(sub.get('stop_after_next_rebill')) is True
                or amount(sub.get('credit', '0')) != '0.00'):
            raise ProviderRejected('Only an active 30- or 90-day subscription with an unchanged schedule can renew early here.')
        for key in ('product', 'next_product'):
            product = sub.get(key) or {}
            if (str(product.get('id')) != line['product_id'] or str(product.get('quantity')) != '1'
                    or product.get('variant_id') not in (None, 0, '0') or product.get('children')):
                raise ProviderRejected('Your next product needs review before an early renewal.')
        if source['contact_id'] and sub.get('contact_id') is not None and str(sub['contact_id']) != source['contact_id']:
            raise ProviderRejected('The subscription owner could not be verified.')
        if str(gateway.get('id')) != source['gateway_id'] or not (
            source['test_order'] is False and str(gateway.get('account_id')) == '250'
            or source['test_order'] is True and source['gateway_id'] == '1' and str(gateway.get('account_id')) == '10'):
            raise ProviderRejected('This subscription does not have a verified Stripe v2 or Dry Run payment route.')
        groups = calculated['data']
        group = groups.get(scheduled)
        if set(groups) != {scheduled} or not isinstance(group, dict):
            raise ProviderRejected('The renewal calculation contains a different schedule.')
        items = group.get('line_items') or {}
        if set(items) != {subscription_id}:
            raise ProviderRejected('The renewal calculation contains other subscriptions.')
        item = items[subscription_id]
        if (str(item.get('product_id')) != line['product_id'] or str(item.get('qty')) != '1'
                or item.get('subscription_id') != subscription_id or flag(item.get('is_bundle')) is not False
                or flag(item.get('is_variant')) is not False or flag(item.get('is_taxable')) is not False):
            raise ProviderRejected('This product needs a separate pricing review before early renewal.')
        total = amount(group.get('total'))
        # Do not carry date/location-dependent tax or shipping estimates into
        # an immediate force bill. Current Fortify plans have neither charge.
        shipping, tax = group.get('shipping') or {}, group.get('tax') or {}
        if (not shipping or not tax or amount(shipping.get('shipping_total_amount')) != '0.00'
                or amount(shipping.get('shipping_tax_amount')) != '0.00'
                or amount(tax.get('sales_tax_amount')) != '0.00' or amount(tax.get('vat_tax_amount')) != '0.00'
                or total != amount(item.get('total')) or Decimal(total) <= 0):
            raise ProviderRejected('The full renewal total needs review before an early charge.')
        result = {'order_id': source['id'], 'subscription_id': subscription_id,
            'amount': total, 'currency': source['currency'], 'scheduled_date': scheduled,
            'next_billing_date': (self.today() + timedelta(days=days)).isoformat(), 'interval_days': days,
            'product_id': line['product_id'], 'gateway_id': source['gateway_id'],
            'source_hash': fingerprint(source), 'configuration_hash': fingerprint({'sub': sub, 'pricing': calculated})}
        return result

    def child(self, quote, scope, child_id=None, require_date=True):
        parent = self.p.read_order(quote['order_id'], **scope)
        if not parent['child_ids']:
            return None
        if len(parent['child_ids']) != 1 or (child_id and parent['child_ids'][0] != str(child_id)):
            raise ProviderUncertain('The renewal order needs reconciliation.')
        child = self.p.read_order(parent['child_ids'][0], **scope)
        if (child['parent_id'] != parent['id'] or child['child_ids'] or child['payment_status'] != 'paid'
                or child['total'] != quote['amount'] or child['currency'] != quote['currency']
                or child['gateway_id'] != quote['gateway_id'] or len(child['products']) != 1
                or child['test_order'] is not parent['test_order']):
            raise ProviderUncertain('The renewal payment needs reconciliation.')
        line = child['products'][0]
        if (line['subscription_id'] != quote['subscription_id'] or line['product_id'] != quote['product_id']
                or line['quantity'] != 1 or line['prepaid'] or line['billing_status'] != 'active'
                or line['billing_model_id'] != parent['products'][0]['billing_model_id']):
            raise ProviderUncertain('The renewal subscription needs reconciliation.')
        if require_date:
            sub = self.p._call_read('GET', '/api/v2/subscriptions/' + quote['subscription_id']).get('data') or {}
            if (line['next_billing_date'] != quote['next_billing_date'] or sub.get('id') != quote['subscription_id']
                    or sub.get('recur_at') != quote['next_billing_date'] or sub.get('status') != 'active'):
                raise ProviderUncertain('The next renewal date needs reconciliation.')
        return child

    def execute(self, quote, scope):
        # One final read after the journal reservation, before the first write.
        fresh = self.p.read_order(quote['order_id'], **scope)
        if fingerprint(fresh) != quote['source_hash'] or quote['next_billing_date'] != (self.today() + timedelta(days=quote['interval_days'])).isoformat():
            raise ProviderRejected('Your subscription changed. Review a fresh renewal quote.')
        try:
            response = self.p.api.call('POST', '/api/v1/order_force_bill', {
                'order_id': quote['order_id'], 'product_id': quote['product_id'],
                'forceGatewayId': int(quote['gateway_id']), 'preserve_force_gateway': 1})
            if str(response.get('response_code')) != '100' or str(response.get('error_found')) != '0':
                raise ProviderUncertain('The renewal outcome needs confirmation.')
            child_id = identifier(response.get('new_order_id') or response.get('order_id'))
            child = self.child(quote, scope, child_id, require_date=False)
            if not child:
                raise ProviderUncertain('The renewal order could not be confirmed.')
            if child['products'][0]['next_billing_date'] != quote['next_billing_date']:
                response = self.p.api.call('POST', '/api/v1/subscription_order_update', {
                    'order_id': child['id'], 'product_id': quote['product_id'],
                    'new_recurring_date': datetime.strptime(quote['next_billing_date'], '%Y-%m-%d').strftime('%m/%d/%Y')})
                if str(response.get('response_code')) != '100':
                    raise ProviderUncertain('The renewal date could not be confirmed.')
            return self.child(quote, scope, child_id)
        except Exception:
            raise ProviderUncertain('We are confirming your payment and next renewal date. Do not pay again.') from None


class RenewalsManager:
    def __init__(self, service):
        self.s = service
        self.provider = RenewalProvider(service.provider, lambda: service.clock())
        site=service.admin.get('site','fortifyhp') or {}
        if site.get('brand_id')=='fortifyhp' and site.get('campaign_id')==195:
            import re
            with service.db() as db:
                for key, raw in db.execute("SELECT id,data FROM admin_config WHERE kind='site_refill_policy'").fetchall():
                    value=json.loads(raw)
                    if value.get('site_id')=='fortifyhp' and re.fullmatch(r'(SEMA|TIRZ|SERM|METFORM|PT141)-(1|3)M-SUB',value.get('sku','')) and 'allow_paid_early_renewal' not in value:
                        value.update(allow_paid_early_renewal=True,revision=value.get('revision',0)+1)
                        db.execute("UPDATE admin_config SET data=? WHERE kind='site_refill_policy' AND id=?",(encoded(value),key))
        with service.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS member_renewal_quotes(
                id TEXT PRIMARY KEY,site_id TEXT NOT NULL,patient_id TEXT NOT NULL,
                order_id TEXT NOT NULL,subscription_id TEXT NOT NULL,details TEXT NOT NULL,
                created REAL NOT NULL,expires REAL NOT NULL,status TEXT NOT NULL,child_order_id TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS member_renewal_once ON member_renewal_quotes(site_id,order_id,subscription_id)
                    WHERE status IN ('processing','uncertain','complete');''')

    def scope(self, row):
        return {'expected_campaign': self.s.site(row['site_id'])[0]['campaign_id'], 'expected_customer_id': row['customer_id']}

    def gate(self, row):
        if hasattr(self.s, 'upgrades') and self.s.upgrades.busy_subscription(row['site_id'], json.loads(row['payload'])['products'][0].get('subscription_id')):
            return 'A replacement checkout exists for this subscription. Open Refills to review it.'
        rule = self.s.rule(row['sku'], row['site_id'])
        if not rule.get('enabled') or not rule.get('allow_paid_early_renewal'):
            return 'Early paid renewal is not enabled for this plan. Contact your care team for help.'
        raw = json.loads(row['payload'])
        if raw.get('test_order') and not rule.get('test_requests_enabled'):
            return 'Early renewal is not enabled for this test order.'
        created = self.s.date(raw.get('created_at'))
        wait = max(int(rule.get('minimum_days', 0)), int(rule.get('early_request_minimum_days', 0)))
        if not created or self.provider.today() < created + timedelta(days=wait):
            return 'You can request another paid refill from ' + ((created + timedelta(days=wait)).isoformat() if created else 'the date confirmed by your care team') + '.'
        with self.s.db() as db:
            previous = db.execute("SELECT max(created) FROM member_renewal_quotes WHERE site_id=? AND subscription_id=? AND status='complete'", (row['site_id'],raw['products'][0].get('subscription_id'))).fetchone()[0]
        with self.s.db() as db:
            if db.execute("SELECT 1 FROM member_renewal_quotes WHERE site_id=? AND subscription_id=? AND status IN ('processing','uncertain')", (row['site_id'],raw['products'][0].get('subscription_id'))).fetchone():
                return 'An earlier renewal is still being confirmed. Check that renewal before making another payment.'
        if previous and self.s.clock() < previous + int(rule.get('early_request_cooldown_days', 7))*86400:
            return 'You recently renewed early. Please wait before requesting another refill.'
        if rule.get('initial_intake_required', True):
            # This also runs inside the charge reservation transaction. Read
            # saved intake state directly; rendering an order can create a care
            # plan using a second writer connection and deadlock the reservation.
            plan = self.s.care.saved_plan(row)
            with self.s.db() as db:
                if plan:
                    intake = db.execute("SELECT status,simulated FROM member_care_intakes WHERE plan_id=? AND task_id='initial'", (plan['id'],)).fetchone()
                else:
                    intake = db.execute('SELECT status,0 AS simulated FROM member_intakes WHERE site_id=? AND order_id=? AND patient_id=?',
                        (row['site_id'],row['order_id'],self.s.care.grant(row))).fetchone()
            if not intake or intake['status'] != 'submitted':
                return 'Complete your health intake for this order before requesting an early refill.'
            if intake['simulated'] and not self.s.care.simulation(row)['available']:
                return 'Complete your health intake without the test clock before requesting an early refill.'
        return ''

    def preview(self, site_id, order_id, subscription_id, patient):
        self.s.order_record(site_id, order_id, patient)
        row = self.s.sync(site_id, order_id)
        self.s.order_record(site_id, order_id, patient)
        with self.s.db() as db:
            existing = db.execute("SELECT * FROM member_renewal_quotes WHERE site_id=? AND order_id=? AND subscription_id=? AND status IN ('processing','uncertain','complete')", (site_id, order_id, subscription_id)).fetchone()
        if existing:
            return {'available': False, 'status': existing['status'], 'quote_id': existing['id'],
                    'reason': 'This renewal is already placed. Refresh your orders.' if existing['status']=='complete' else 'We are confirming your earlier renewal. Check its status before trying again.'}
        try:
            quote = self.provider.quote(order_id, subscription_id, **self.scope(row))
        except ProviderError as exc:
            return {'available': False, 'reason': str(exc)}
        reason = self.gate(row)
        if reason:
            return {'available': False, 'amount': quote['amount'], 'currency': quote['currency'], 'scheduled_date': quote['scheduled_date'], 'reason': reason}
        qid, now = 'renew_' + secrets.token_urlsafe(24), self.s.clock()
        with self.s.db() as db:
            db.execute("DELETE FROM member_renewal_quotes WHERE status='ready' AND expires<?", (now,))
            db.execute('INSERT INTO member_renewal_quotes VALUES(?,?,?,?,?,?,?,?,?,NULL)', (qid,site_id,patient['id'],order_id,subscription_id,encoded(quote),now,now+300,'ready'))
        return {k: quote[k] for k in ('amount','currency','scheduled_date','next_billing_date','interval_days')} | {'available': True, 'quote_id': qid, 'expires_at': now+300}

    def finish(self, saved, child):
        self.s.sync(saved['site_id'], saved['order_id'])
        self.s.order_record(saved['site_id'], child['id'], {'id': saved['patient_id']})
        with self.s.db() as db:
            db.execute("UPDATE member_renewal_quotes SET status='complete',child_order_id=? WHERE id=?", (child['id'],saved['id']))
            db.execute("UPDATE member_actions SET status='complete' WHERE id=?", (saved['id'],))
        return {'status': 'complete', 'order_id': child['id'], 'next_billing_date': json.loads(saved['details'])['next_billing_date']}

    def confirm(self, site_id, order_id, subscription_id, body, patient):
        row = self.s.order_record(site_id, order_id, patient)
        with self.s.db() as db:
            saved = db.execute('SELECT * FROM member_renewal_quotes WHERE id=? AND site_id=? AND patient_id=? AND order_id=? AND subscription_id=?', (body.quote_id,site_id,patient['id'],order_id,subscription_id)).fetchone()
        if not saved:
            raise HTTPException(404, 'Renewal quote not found.')
        saved = dict(saved); quote = json.loads(saved['details']);scope = self.scope(row)
        if saved['status']=='complete':
            return {'status':'complete','order_id':saved['child_order_id'],'next_billing_date':quote['next_billing_date']}
        if saved['status'] in ('processing','uncertain'):
            try:
                child = self.provider.child(quote, scope)
                if child:return self.finish(saved, child)
            except (ProviderError, HTTPException):pass
            raise HTTPException(409,'We are confirming your earlier payment. It will not be charged again.')
        if not body.confirmed or saved['status']!='ready' or saved['expires']<=self.s.clock():
            raise HTTPException(409,'Review a fresh price and confirm before renewing.')
        row = self.s.sync(site_id, order_id)
        reason = self.gate(row)
        if reason:raise HTTPException(409,reason)
        try:
            fresh = self.provider.quote(order_id, subscription_id, **scope)
        except ProviderError as exc:raise HTTPException(409,str(exc)) from None
        if fresh != quote:raise HTTPException(409,'Your renewal price or schedule changed. Review a fresh quote.')
        with self.s.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM member_renewal_quotes WHERE site_id=? AND order_id=? AND subscription_id=? AND status IN ('processing','uncertain','complete')",(site_id,order_id,subscription_id)).fetchone():
                raise HTTPException(409,'This renewal is already being processed. Check its status.')
            if db.execute("SELECT 1 FROM member_actions WHERE site_id=? AND subscription_id=? AND status IN ('pending','uncertain')",(site_id,subscription_id)).fetchone():
                raise HTTPException(409,'An earlier subscription change needs confirmation.')
            reason=self.gate(self.s.order_record(site_id,order_id,patient))
            if reason:raise HTTPException(409,reason)
            if saved['expires']<=self.s.clock():raise HTTPException(409,'Your quote expired. Review a fresh price.')
            db.execute("UPDATE member_renewal_quotes SET status='processing' WHERE id=? AND status='ready'",(saved['id'],))
            db.execute('INSERT INTO member_actions VALUES(?,?,?,?,?,?,?,?,?)',(saved['id'],site_id,patient['id'],order_id,subscription_id,'renew_early',saved['id'],'pending',self.s.clock()))
        try:
            child = self.provider.execute(quote, scope)
            return self.finish(saved,child)
        except ProviderRejected as exc:
            with self.s.db() as db:
                db.execute("UPDATE member_renewal_quotes SET status='rejected' WHERE id=?",(saved['id'],))
                db.execute("UPDATE member_actions SET status='rejected' WHERE id=?",(saved['id'],))
            raise HTTPException(409,str(exc)) from None
        except Exception:
            with self.s.db() as db:
                db.execute("UPDATE member_renewal_quotes SET status='uncertain' WHERE id=?",(saved['id'],))
                db.execute("UPDATE member_actions SET status='uncertain' WHERE id=?",(saved['id'],))
            raise HTTPException(409,'We are confirming your payment and next renewal date. Do not pay again.') from None

    def attach(self, router, auth):
        @router.get('/orders/{order_id}/subscriptions/{subscription_id}/renewal')
        def preview(site_id:str,order_id:str,subscription_id:str,patient=Depends(auth)):
            return self.preview(site_id,order_id,subscription_id,patient)
        @router.post('/orders/{order_id}/subscriptions/{subscription_id}/renewal')
        def confirm(site_id:str,order_id:str,subscription_id:str,body:RenewConsent,patient=Depends(auth)):
            return self.confirm(site_id,order_id,subscription_id,body,patient)
