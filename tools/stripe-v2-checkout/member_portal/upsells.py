"""Optional site-owned post-purchase offers. No automatic charges or write retries.

Card-on-file sales stay disabled until the deployment has verified that exact
Sticky gateway's contract. One-time, non-prepaid offers only in this release.
"""
import hashlib
import json
import os
import secrets
import threading
from decimal import Decimal
from urllib.parse import urlsplit, parse_qs
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from catalog import resolve, quote
from plans import choice_id


def key(value):
    return hashlib.sha256(value.encode()).hexdigest()


class OfferSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = False
    placements: list[str] = Field(default_factory=lambda: ['thank_you'], max_length=3)
    plan_ids: list[str] = Field(default_factory=list, max_length=3)


class BuyOffer(BaseModel):
    model_config = ConfigDict(extra='forbid')
    quote_id: str = Field(min_length=20, max_length=100)
    confirmed: bool


class PostPurchaseOffers:
    def __init__(self, service):
        self.s = service
        self.lock = threading.RLock()

    def settings(self, site):
        return self.s.admin.get('postpurchase_settings', site) or OfferSettings().model_dump()

    def available_gateway(self, gateway):
        return str(gateway) in os.environ.get('STICKY_CARD_ON_FILE_VERIFIED_GATEWAYS', '').split(',')

    def choices(self, site):
        # A store plan ID is an opaque ID derived from an enabled exact choice,
        # never a caller-supplied amount/product/gateway.
        return [p for p in self.s.store_catalog(site)['plans'] if p['recurring'] is False]

    def context(self, site, selected):
        plan = self.s.admin.get('plan_checkout', selected['checkout_id'])
        if not plan or plan.get('site_id') != site or not plan.get('enabled') or plan.get('visibility') != 'public':
            raise HTTPException(409, 'This product is no longer available.')
        query = parse_qs(urlsplit(selected['checkout_url']).query)
        sku, option = query['sku'][0], query['option'][0]
        link, brand = self.s.admin.link(choice_id(plan['id'], sku, query.get('purchase_option_id', [''])[0]))
        if link['brand_id'] != self.s.site(site)[0]['brand_id'] or int(link['campaign_id']) != int(self.s.site(site)[0]['campaign_id']):
            raise HTTPException(409, 'This product does not belong to this site.')
        catalog = self.s.admin.filter_catalog(resolve(self.s.admin.api, plan['campaign_id'], sku, allowed_keys=link['options']), link, brand)
        chosen = next((o for o in catalog['options'] if o['key'] == option), None)
        if not chosen or chosen.get('prepaidCycles') or chosen.get('recurring') or chosen.get('blockedReason') or catalog['blockedReason']:
            raise HTTPException(409, 'Use the regular checkout for this plan.')
        return link, catalog, option

    def offers(self, receipt, placement='thank_you'):
        order, _ = self.s.receipt_order(receipt)
        with self.s.db() as db:
            if not db.execute('SELECT 1 FROM member_grants WHERE site_id=? AND order_id=?', (order['site_id'], order['order_id'])).fetchone():
                return {'offers': []}
        settings = self.settings(order['site_id'])
        if not settings['enabled'] or placement not in settings['placements']:
            return {'offers': []}
        result = []
        for selected in self.choices(order['site_id']):
            if selected['plan_id'] not in settings['plan_ids'] or selected['sku'] == order['sku']:
                continue
            try:
                link, catalog, option = self.context(order['site_id'], selected)
                source = json.loads(order['payload'])
                if catalog['gatewayId'] != int(source['gateway_id']) or not self.available_gateway(catalog['gatewayId']):
                    continue
                contact = dict(source['shipping_address'], email=source['customer']['email'])
                shipping = int(source['shipping_id']) if source.get('shipping_id') else None
                priced = quote(self.s.admin.api, catalog, option, shipping, contact)
                token = secrets.token_urlsafe(24)
                record = {'source_order': order['order_id'], 'site_id': order['site_id'], 'plan_id': selected['plan_id'],
                    'shipping_address': source['shipping_address'], 'placement': placement, 'expires': self.s.clock() + 600, 'quote': priced, 'link_id': link['id']}
                self.s.admin.put('postpurchase_quote', key(token), record)
                result.append({'quote_id': token, 'name': selected['product_name'], 'plan_name': selected['plan_name'],
                    'amount': priced['amount'], 'currency': priced['currency'], 'purchase_type': 'once',
                    'terms': 'One-time purchase. Uses the payment method and delivery address from this order.',
                    'expires_at': record['expires']})
            except Exception:
                # Optional commerce never prevents access to the purchased care.
                continue
        return {'offers': result}

    def buy(self, receipt, body, ip):
        order, _ = self.s.receipt_order(receipt)
        record = self.s.admin.get('postpurchase_quote', key(body.quote_id))
        if not record or record['site_id'] != order['site_id'] or record['source_order'] != order['order_id']:
            raise HTTPException(404, 'Offer not found for this purchase.')
        sale_key = key(order['site_id'] + ':' + order['order_id'] + ':' + record['plan_id'])
        with self.lock:
            saved = self.s.admin.get('postpurchase_sale', sale_key)
            if saved:
                return self.sale_public(saved)
            if not body.confirmed:
                raise HTTPException(422, 'Confirm the displayed purchase price.')
            settings = self.settings(order['site_id'])
            if not settings['enabled'] or record['placement'] not in settings['placements'] or record['plan_id'] not in settings['plan_ids']:
                raise HTTPException(409, 'This offer is no longer available.')
            if record['expires'] <= self.s.clock():
                raise HTTPException(409, 'This price expired. Refresh the available products.')
            selected = next((p for p in self.choices(order['site_id']) if p['plan_id'] == record['plan_id']), None)
            if not selected:
                raise HTTPException(409, 'This product is no longer available.')
            link, catalog, option = self.context(order['site_id'], selected)
            q = record['quote']
            # A deployment allowlist is evidence of gateway verification, not an
            # admin checkbox that can bypass it.
            if not self.available_gateway(catalog['gatewayId']):
                raise HTTPException(409, 'Saved-card purchasing is not enabled for this payment connection.')
            source = self.s.provider.read_order(order['order_id'], expected_campaign=q['campaignId'], expected_customer_id=order['customer_id'])
            if source['payment_status'] != 'paid' or str(source['gateway_id']) != str(q['gatewayId']):
                raise HTTPException(409, 'The original payment needs review.')
            if source.get('shipping_address') != record.get('shipping_address'):
                raise HTTPException(409, 'The delivery address changed. Refresh this offer before buying.')
            fresh = quote(self.s.admin.api, catalog, option, q['shippingId'], dict(source['shipping_address'], email=source['customer']['email']))
            if any(fresh[k] != q[k] for k in ('amount', 'currency', 'fingerprint', 'gatewayId', 'selection')):
                raise HTTPException(409, 'This price or product changed. Refresh before buying.')
            attempt = self.s.store.create(q['campaignId'], q['sku'], link['id'])
            self.s.store.claim('new', 'authorizing', attempt, contact=receipt['contact'], quote=json.dumps(q))
            saved = {'status': 'needs_review', 'attempt_id': attempt, 'order_id': None,
                     'site_id': order['site_id'], 'created': self.s.clock()}
            # Persist BEFORE the irreversible request. A crash/timeout holds the
            # sale, and subsequent clicks cannot issue a second provider write.
            self.s.admin.put('postpurchase_sale', sale_key, saved)
            opt = q['option']
            payload = {'previousOrderId': order['order_id'], 'campaignId': q['campaignId'],
                'forceGatewayId': q['gatewayId'], 'preserve_force_gateway': 1,
                'initializeNewSubscription': 1, 'ipAddress': ip,
                'offers': [{'offer_id': opt['offerId'], 'product_id': opt['productId'],
                    'billing_model_id': opt['billingModelId'], 'quantity': 1, 'step_num': 2}]}
            if q['shippingId'] is not None: payload['shippingId'] = q['shippingId']
            try:
                response = self.s.admin.api.call('POST', '/api/v1/new_order_card_on_file', payload)
                if str(response.get('response_code')) != '100' or not str(response.get('order_id', '')).isdigit():
                    return self.sale_public(saved)
                saved['order_id'] = str(response['order_id'])
                self.s.admin.put('postpurchase_sale', sale_key, saved)
                actual = self.s.provider.read_order(saved['order_id'], expected_campaign=q['campaignId'], expected_customer_id=order['customer_id'])
                products = actual['products']
                valid = (actual['payment_status'] == 'paid' and str(actual['gateway_id']) == str(q['gatewayId'])
                    and actual['currency'].upper() == q['currency'].upper() and Decimal(actual['total']) == Decimal(q['total'])
                    and len(products) == 1 and str(products[0]['product_id']) == str(opt['productId'])
                    and str(products[0]['offer_id']) == str(opt['offerId']) and str(products[0]['billing_model_id']) == str(opt['billingModelId'])
                    and products[0]['quantity'] == 1 and products[0]['is_recurring'] is False)
                if not valid: return self.sale_public(saved)
                self.s.store.claim('authorizing', 'captured', attempt, order_id=saved['order_id'])
                self.s.sync(order['site_id'], saved['order_id'])
                with self.s.db() as db:
                    grant = db.execute('SELECT patient_id FROM member_grants WHERE site_id=? AND order_id=?', (order['site_id'], order['order_id'])).fetchone()
                    if grant:
                        db.execute('INSERT OR IGNORE INTO member_grants VALUES(?,?,?,?,?)',
                            (order['site_id'], saved['order_id'], grant['patient_id'], self.s.clock(), 'verified_postpurchase'))
                saved['status'] = 'paid'
                self.s.admin.put('postpurchase_sale', sale_key, saved)
            except Exception:
                pass
            return self.sale_public(saved)

    @staticmethod
    def sale_public(saved):
        return {'status': saved['status'], 'order_id': saved['order_id'],
            'message': 'Your additional order is placed. Open your member portal for its intake and next steps.' if saved['status'] == 'paid'
            else 'We’re confirming this payment. Please contact support before trying again. Your original purchase is saved.'}

    def attach_admin(self, app):
        @app.get('/api/admin/sites/{site_id}/postpurchase')
        def get_settings(site_id: str, req: Request):
            self.s.admin.authenticated(req); self.s.site(site_id)
            return {'settings': self.settings(site_id), 'plans': self.choices(site_id),
                'notice': 'Only verified saved-card gateways can show offers. One-time products only; no automatic purchases.'}

        @app.post('/api/admin/sites/{site_id}/postpurchase')
        def save_settings(site_id: str, body: OfferSettings, req: Request):
            self.s.admin.authenticated(req, True); self.s.site(site_id)
            if any(p not in ('thank_you', 'before_intake', 'after_intake') for p in body.placements):
                raise HTTPException(422, 'Choose a supported post-purchase placement.')
            allowed = {p['plan_id'] for p in self.choices(site_id)}
            if any(p not in allowed for p in body.plan_ids):
                raise HTTPException(422, 'Choose published one-time plans from this site.')
            self.s.admin.put('postpurchase_settings', site_id, body.model_dump())
            return {'saved': True, 'settings': body.model_dump()}
