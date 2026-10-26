"""Campaign-scoped catalog and authoritative Sticky quotes; never changes configuration."""
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
import threading
import time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import copy
import weakref
from prepaid import cycles_for, renewal_for
from external_fulfillment import fortifyhp_prepaid_supported


class CatalogError(Exception):
    pass


class CouponError(CatalogError):
    pass


class CampaignSnapshots:
    """Brief setup reuse for display/quotes; financial writes always force a read.

    Owned by one application/API client. No customer, quote, gateway credential
    or payment data is cached. Product prices, coupon profiles and calculated
    totals still come from Sticky on every quote. Never serve expired-on-error.
    """
    def __init__(self, api, ttl=120, limit=64, clock=time.monotonic):
        self.api, self.ttl, self.limit, self.clock = api, ttl, limit, clock
        self.entries = OrderedDict()
        self.guard = threading.Lock()
        self.locks = weakref.WeakValueDictionary()

    def read(self, campaign_id, fresh=False):
        with self.guard:
            lock = self.locks.get(campaign_id)
            if lock is None:
                lock = threading.Lock()
                self.locks[campaign_id] = lock
        with lock:
            with self.guard:
                entry = self.entries.get(campaign_id)
                if not fresh and entry and entry[0] > self.clock():
                    self.entries.move_to_end(campaign_id)
                    return copy.deepcopy(entry[1])
                self.entries.pop(campaign_id, None)
            c = self.api.detail(f'/api/v2/campaigns/{campaign_id}')
            # Retain catalog configuration only, never embedded provider secrets.
            keys = ('id', 'c_id', 'name', 'is_active', 'is_archived', 'gateway_id',
                    'tax_provider_id', 'fulfillment_id', 'countries', 'shipping_profiles',
                    'offers', 'volume_discounts', 'fraud_providers', 'postback_profiles',
                    'email_provider_id', 'membership_provider_id', 'coupon_profiles',
                    'payment_methods')
            value = {k: copy.deepcopy(c[k]) for k in keys if k in c}
            value['alternative_payments'] = [
                {'payment_method': p.get('payment_method'),
                 'provider': {k: p.get('provider', {}).get(k) for k in ('id', 'account_id')}}
                for p in c.get('alternative_payments', [])]
            with self.guard:
                self.entries[campaign_id] = (self.clock() + self.ttl, value)
                self.entries.move_to_end(campaign_id)
                while len(self.entries) > self.limit:
                    self.entries.popitem(last=False)
            return copy.deepcopy(value)


class AuthorizationCampaignReuse:
    """One-use campaign setup from THIS authorization, never a shared display cache.

    Only configuration is retained. Prices, offers, gateway profile and calculated
    total must still be fetched at capture. External campaign-only edits can take
    up to 30 seconds to affect an already-authorized payment; stale/missing tickets
    require the full campaign read. No persistence or renewal of the deadline.
    """
    def __init__(self, ttl=30, limit=128, clock=time.monotonic):
        self.ttl, self.limit, self.clock = ttl, limit, clock
        self.entries = OrderedDict()
        self.guard = threading.Lock()

    def remember(self, attempt, campaign, quote_id, intent, snapshot, checked_at):
        with self.guard:
            now = self.clock()
            for key, value in list(self.entries.items()):
                if value[0] <= now:
                    self.entries.pop(key, None)
            if checked_at + self.ttl <= now:
                return
            self.entries[attempt] = (checked_at + self.ttl, campaign, quote_id, intent, copy.deepcopy(snapshot))
            self.entries.move_to_end(attempt)
            while len(self.entries) > self.limit:
                self.entries.popitem(last=False)

    def consume(self, attempt, campaign, quote_id, intent):
        with self.guard:
            value = self.entries.pop(attempt, None)
            if value and value[0] > self.clock() and value[1:4] == (campaign, quote_id, intent):
                return {'snapshot': copy.deepcopy(value[4]), 'expires': value[0]}
        return None

    def discard(self, attempt):
        with self.guard:
            self.entries.pop(attempt, None)


class RoutingHints:
    """Bounded nonsecret IDs only, to schedule fresh independent reads together."""
    def __init__(self, ttl=120, limit=256, clock=time.monotonic):
        self.ttl, self.limit, self.clock = ttl, limit, clock
        self.entries = OrderedDict()
        self.guard = threading.Lock()

    def get(self, key):
        with self.guard:
            entry = self.entries.get(key)
            if entry and entry[0] > self.clock():
                self.entries.move_to_end(key)
                return entry[1]
            self.entries.pop(key, None)

    def remember(self, key, gateway_id):
        if not isinstance(gateway_id, int) or gateway_id <= 0:
            return
        with self.guard:
            self.entries[key] = (self.clock() + self.ttl, gateway_id)
            self.entries.move_to_end(key)
            while len(self.entries) > self.limit:
                self.entries.popitem(last=False)


def coupon_for(api, catalog, code):
    """Read only profiles assigned to this campaign; never accept client discounts."""
    candidates = sorted(catalog.get('couponProfiles', []), key=lambda p: str(p.get('name', '')).upper() != code.upper())
    def find(candidate):
        profile = api.detail('/api/v2/coupons/' + str(int(candidate['id'])))
        codes = [p for p in profile.get('promo_codes', []) if str(p.get('code', '')).upper() == code.upper()
                 and enabled(p.get('is_active')) and not enabled(p.get('is_deleted'))]
        if codes and enabled(profile.get('is_active')):
            return profile, codes[0]
        return None
    # Most profiles use the code as their name (including our test coupon).
    # For custom profile names, check assigned profiles concurrently instead
    # of adding a separate network round trip for each invalid-code candidate.
    preferred = [p for p in candidates if str(p.get('name','')).upper() == code.upper()]
    matches = [result for p in preferred if (result := find(p))]
    if not matches:
        remaining = [p for p in candidates if p not in preferred]
        with ThreadPoolExecutor(max_workers=4) as pool:
            matches = [r for r in pool.map(find, remaining) if r]
    if not matches:
        raise CouponError('This discount code is not available for this site.')
    profile, promo = matches[0]
    percent = money(profile.get('discount_percent', profile.get('discount_pct', 0)))
    if int(profile.get('type_id', 0)) != 1 or enabled(profile.get('is_bogo')) or not 0 < percent < 100:
        raise CouponError('This discount is not supported by this checkout.')
    return {'code': promo['code'], 'profileId': int(profile['id']), 'percent': str(percent),
            'lifetime': enabled(profile.get('is_lifetime'))}


def money(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0 or result != result.quantize(Decimal('.01')):
            raise ValueError()
        return result
    except (ValueError, InvalidOperation):
        raise CatalogError('Sticky returned an invalid monetary amount') from None


def enabled(value):
    return value not in (None, False, 0, '0', '')


def resolve(api, campaign_id, sku, allowed_keys=None, gateway_hint=None, campaign_loader=None, fresh_offers=False):
    allowed = None
    if allowed_keys is not None:
        try:
            allowed = {tuple(int(part) for part in key.split(':')) for key in allowed_keys}
            if not allowed or any(len(key) != 3 or min(key) <= 0 for key in allowed):raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise CatalogError('The published payment choices are invalid') from None
    # Display/quote callers may reuse a bounded setup snapshot. Authorization
    # and capture supply a forced-fresh loader. Products/gateway remain fresh.
    with ThreadPoolExecutor(max_workers=8) as pool:
        campaign_future = pool.submit(campaign_loader) if campaign_loader else pool.submit(api.detail, f'/api/v2/campaigns/{campaign_id}')
        hinted_gateway = pool.submit(api.detail, f'/api/v2/providers/payment/profiles/{gateway_hint}') if allowed is not None and gateway_hint else None
        c = campaign_future.result()
        if enabled(c.get('is_archived')) or c.get('is_active') in (False, 0, '0'):
            raise CatalogError('This campaign is inactive')
        offers = c.get('offers', [])
        if allowed is not None:
            offers = [o for o in offers if int(o['id']) in {key[0] for key in allowed}]
        def offer_detail(o):
            return o if 'products' in o and not fresh_offers else api.detail('/api/v2/offers/' + str(o['id']))
        offers = list(pool.map(offer_detail, offers))
        offers = [o for o in offers if not enabled(o.get('is_archived'))]
        ids = sorted({int(p['id']) for o in offers for p in o.get('products', [])
            if allowed is None or any(key[:2] == (int(o['id']), int(p['id'])) for key in allowed)})
        links = [x.get('provider', {}) for x in c.get('alternative_payments', []) if x.get('payment_method') == 'stripe_link']
        gateway_future = None
        if allowed is not None and len(links) == 1 and int(links[0].get('account_id') or 0) == 250:
            gateway_id = int(links[0]['id'])
            gateway_future = hinted_gateway if gateway_id == gateway_hint and hinted_gateway else pool.submit(api.detail, f'/api/v2/providers/payment/profiles/{gateway_id}')
        products = list(pool.map(lambda i: api.detail(f'/api/v2/products/{i}'), ids))
        gateway = gateway_future.result() if gateway_future else None
    matched = {i: p for i, p in zip(ids, products) if p.get('sku') == sku and not enabled(p.get('archived_flag'))}
    if not matched:
        raise CatalogError('This SKU is not in an active offer on this campaign')
    options = []
    for o in offers:
        for p in o.get('products', []):
            pid = int(p['id'])
            if pid not in matched:
                continue
            product = matched[pid]
            reason = ''
            prepaid_cycles=None
            try:prepaid_cycles=cycles_for(o)
            except (ValueError,TypeError):reason='This prepaid configuration needs additional setup before payment.'
            if any(enabled(o.get(k)) for k in ('is_series', 'is_seasonal', 'is_trial')):
                reason = 'This offer needs a prepaid, series, seasonal or trial selection that this checkout does not yet support.'
            if any(enabled(product.get(k)) for k in ('is_bundle', 'is_variant_enabled')):
                reason = 'This product needs bundle or variant selections that this checkout does not yet support.'
            if prepaid_cycles and (enabled(product.get('is_shippable')) or enabled(product.get('taxable',product.get('is_taxable')))) and not fortifyhp_prepaid_supported(c, product, o):
                reason='Prepaid medication fulfillment and taxes require a verified release workflow. This version supports non-shippable test products only.'
            for m in o.get('offer_billing_models') or o.get('billing_models', []):
                if enabled(m.get('is_archived')):
                    continue
                mid = int(m['id'])
                if allowed is not None and (int(o['id']), pid, mid) not in allowed:
                    continue
                days = int(m.get('days') or 0)
                model_reason = reason
                if prepaid_cycles and (mid==2 or enabled(m.get('discount'))):model_reason='Prepaid requires a recurring shipment interval without a model discount'
                if mid != 2 and (days <= 0 or int((m.get('type') or {}).get('id') or 0) != 1):
                    model_reason = model_reason or 'This billing schedule needs additional configuration before payment.'
                options.append({'key': f"{o['id']}:{pid}:{mid}", 'offerId': int(o['id']), 'productId': pid,
                    'billingModelId': mid, 'name': product.get('name', sku), 'offerName': o.get('name', ''),
                    'modelName': m.get('name', ''), 'recurring': mid != 2, 'days': days,
                    **({'prepaidCycles':prepaid_cycles,'renewal':renewal_for(o),'renewalDays':days*prepaid_cycles if renewal_for(o) else None,'upfrontPrice':str(money(product.get('price'))*prepaid_cycles)} if prepaid_cycles else {}),
                    'basePrice': str(money(product.get('price'))), 'shippable': enabled(product.get('is_shippable')), 'blockedReason': model_reason})
    if not options:
        raise CatalogError('No active billing model is configured for this SKU')
    route_error = ''
    gateway_id = None
    public = None
    currency = None
    methods = {x.get('value') for x in c.get('payment_methods', [])}
    links = [x.get('provider', {}) for x in c.get('alternative_payments', []) if x.get('payment_method') == 'stripe_link']
    if 'stripe_link' not in methods or len(links) != 1 or int(links[0].get('account_id') or 0) != 250:
        route_error = 'Enable Stripe Link with a Stripe Connect v2 gateway on this campaign to accept payment here.'
    else:
        gateway_id = int(links[0]['id'])
        g = gateway if gateway is not None else api.detail(f'/api/v2/providers/payment/profiles/{gateway_id}')
        fields = g.get('fields', {}).get('account_fields', {})
        public = fields.get('publishable_key', '')
        raw_currency = g.get('currency')
        currency = (raw_currency.get('code') or raw_currency.get('name', '')) if isinstance(raw_currency, dict) else raw_currency
        currency = str(currency or '').lower()
        if int(g.get('account_id') or 0) != 250 or not public.startswith(('pk_live_', 'pk_test_')):
            route_error = 'The campaign Stripe Connect v2 public configuration is unavailable.'
        elif any(enabled(fields.get(k)) for k in ('capture_on_shipment', 'enable_delayed_capture')):
            route_error = 'This gateway uses delayed capture; this immediate-capture checkout cannot submit its orders.'
        elif currency not in {'usd', 'eur', 'gbp', 'cad', 'aud', 'nzd', 'chf'}:
            route_error = 'The gateway currency needs a supported minor-unit configuration.'
    result = {'campaignId': campaign_id, 'campaignName': c.get('name', ''), 'sku': sku,
        'options': options, 'shipping': [{'id': int(s['id']), 'name': s['name']} for s in c.get('shipping_profiles', [])],
        'countries': [{'code': x['iso_2'], 'name': x['name']} for x in c.get('countries', [])],
        'gatewayId': gateway_id, 'publishableKey': public if not route_error else None,
        'currency': currency, 'blockedReason': route_error,
        'couponProfiles': [{'id':p['id'], 'name':p.get('name','')} for p in c.get('coupon_profiles', [])],
        'dollarTestSafe': all(c.get(k) in (None,0,'0',[]) for k in ('fulfillment_id','tax_provider_id','email_provider_id','membership_provider_id','postback_profiles')) and all(not enabled(p.get('is_shippable')) and not enabled(p.get('taxable',p.get('is_taxable'))) for p in matched.values())}
    # Detect changes to offers, billing terms, tax/fulfillment/routing without exposing provider secrets.
    stable_campaign = {k:c.get(k) for k in ('id','c_id','is_active','is_archived','tax_provider_id','fulfillment_id',
        'countries','shipping_profiles','offers','volume_discounts','fraud_providers','postback_profiles',
        'email_provider_id','membership_provider_id','coupon_profiles')}
    # Another successful cart item increments usage counts. That is not a
    # pricing change; Sticky still checks remaining uses on every quote.
    stable_campaign['coupon_profiles'] = [{k:p.get(k) for k in ('id','type_id','discount_amount','discount_percent',
        'discount_amt','discount_pct','is_lifetime','is_active','is_free_shipping','expires_at','limits','products')}
        for p in c.get('coupon_profiles', [])]
    scope = {'publishedChoices':sorted(allowed),'selectedOffers':offers} if allowed is not None else {}
    result['fingerprint'] = hashlib.sha256(json.dumps({**scope, 'campaign': stable_campaign, 'products': products, 'gateway': {
        'id': gateway_id, 'public': public, 'currency': currency, 'error': route_error}}, sort_keys=True).encode()).hexdigest()
    if allowed is not None:result['catalogVersion'] = 2
    return result


def quote(api, catalog, selection, shipping_id, contact, coupon_code=''):
    if catalog['blockedReason']:
        raise CatalogError(catalog['blockedReason'])
    option = next((o for o in catalog['options'] if o['key'] == selection), None)
    if not option:
        raise CatalogError('Select a billing option from this campaign and SKU')
    if option['blockedReason']:
        raise CatalogError(option['blockedReason'])
    coupon = coupon_for(api, catalog, coupon_code) if coupon_code else None
    if coupon and option.get('dollarTest'):
        raise CouponError('Discount codes cannot be combined with $1 testing.')
    if contact['country'] not in {c['code'] for c in catalog['countries']}:
        raise CatalogError('This country is not enabled for this campaign')
    if shipping_id not in {s['id'] for s in catalog['shipping']}:
        if option['shippable'] or shipping_id is not None:
            raise CatalogError('Select an enabled campaign shipping method')
    line = {'id': option['offerId'], 'product_id': option['productId'], 'billing_model_id': option['billingModelId'], 'quantity': 1}
    if option.get('prepaidCycles'):line['prepaid_cycles']=option['prepaidCycles']
    if option.get('dollarTest'):line['price']=option['testUnitPrice']
    body = {'campaign_id': catalog['campaignId'], 'offers': [line], 'use_tax_provider': 1,
        'location': {'country': contact['country'], 'postal_code': contact['postal_code'], 'state': contact['region']}}
    if shipping_id is not None:
        body['shipping_id'] = shipping_id
    if coupon:
        body['promo'] = {'code': coupon['code'], 'email': contact['email']}
    data = api.call('POST', '/api/v2/order_total/calculate', body).get('data', {})
    total = money(data.get('total'))
    discount = Decimal('0')
    if coupon:
        applied = [d for d in data.get('discounts', []) if d.get('type') == 'promo' and str(d.get('code','')).upper() == coupon['code'].upper()]
        if len(applied) != 1 or applied[0].get('valid') not in (True, 1, '1'):
            raise CouponError('This discount code is invalid, expired or has reached its usage limit.')
        discount = money(applied[0].get('total'))
        if discount <= 0:
            raise CouponError('This discount does not apply to the selected plan.')
    if option.get('dollarTest') and total != Decimal('1.00'):
        raise CatalogError('Sticky did not confirm the $1 test total; no payment submitted')
    lines = data.get('line_items', [])
    if total <= 0 or len(lines) != 1 or str(lines[0].get('id')) != str(option['productId']) or int(lines[0].get('qty', 0)) != 1:
        raise CatalogError('Sticky did not return a supported positive single-product total')
    if option.get('prepaidCycles'):
        prepaid=lines[0].get('prepaid') or {}
        if not enabled(lines[0].get('is_prepaid')) or str(prepaid.get('term'))!=str(option['prepaidCycles']) or money(prepaid.get('total'))!=money(option['upfrontPrice']) or total+discount!=money(option['upfrontPrice']):
            raise CatalogError('Sticky prepaid total or shipment count did not match; no payment submitted')
    return {'amount': int(total * 100), 'total': str(total), 'currency': catalog['currency'],
        'selection': selection, 'shippingId': shipping_id, 'option': option,
        'campaignId': catalog['campaignId'], 'sku': catalog['sku'], 'gatewayId': catalog['gatewayId'],
        'fingerprint': catalog['fingerprint'], 'catalogVersion':catalog.get('catalogVersion',1),
        **({'coupon':coupon, 'discountAmount':int(discount*100), 'subtotalAmount':int((total+discount)*100),
            'renewalPrice':str((money(option.get('upfrontPrice',option['basePrice'])) *
                (1-Decimal(coupon['percent'])/100 if coupon['lifetime'] else 1)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))} if coupon else {})}
