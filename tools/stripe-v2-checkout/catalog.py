"""Campaign-scoped catalog and authoritative Sticky quotes; never changes configuration."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, InvalidOperation
import hashlib
import json
from prepaid import cycles_for, renewal_for
from external_fulfillment import fortifyhp_prepaid_supported


class CatalogError(Exception):
    pass


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


def resolve(api, campaign_id, sku, allowed_keys=None):
    c = api.detail(f'/api/v2/campaigns/{campaign_id}')
    if enabled(c.get('is_archived')) or c.get('is_active') in (False, 0, '0'):
        raise CatalogError('This campaign is inactive')
    offers = c.get('offers', [])
    allowed = None
    if allowed_keys is not None:
        try:
            allowed = {tuple(int(part) for part in key.split(':')) for key in allowed_keys}
            if not allowed or any(len(key) != 3 or min(key) <= 0 for key in allowed):raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise CatalogError('The published payment choices are invalid') from None
        # Only server-owned published keys reach this path. Campaign membership
        # remains authoritative; never fetch arbitrary/account-wide SKU matches.
        offers = [o for o in offers if int(o['id']) in {key[0] for key in allowed}]
    def offer_detail(o):
        return o if 'products' in o else api.detail('/api/v2/offers/' + str(o['id']))
    with ThreadPoolExecutor(max_workers=8) as pool:
        offers = list(pool.map(offer_detail, offers))
    offers = [o for o in offers if not enabled(o.get('is_archived'))]
    ids = sorted({int(p['id']) for o in offers for p in o.get('products', [])
        if allowed is None or any(key[:2] == (int(o['id']), int(p['id'])) for key in allowed)})
    links = [x.get('provider', {}) for x in c.get('alternative_payments', []) if x.get('payment_method') == 'stripe_link']
    with ThreadPoolExecutor(max_workers=8) as pool:
        # The gateway and selected product are independent read-only requests.
        gateway_future = pool.submit(api.detail, f"/api/v2/providers/payment/profiles/{int(links[0]['id'])}") if allowed is not None and len(links)==1 and int(links[0].get('account_id') or 0)==250 else None
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
        'dollarTestSafe': all(c.get(k) in (None,0,'0',[]) for k in ('fulfillment_id','tax_provider_id','email_provider_id','membership_provider_id','postback_profiles')) and all(not enabled(p.get('is_shippable')) and not enabled(p.get('taxable',p.get('is_taxable'))) for p in matched.values())}
    # Detect changes to offers, billing terms, tax/fulfillment/routing without exposing provider secrets.
    stable_campaign = {k:c.get(k) for k in ('id','c_id','is_active','is_archived','tax_provider_id','fulfillment_id',
        'countries','shipping_profiles','offers','volume_discounts','fraud_providers','postback_profiles',
        'email_provider_id','membership_provider_id','coupon_profiles')}
    scope = {'publishedChoices':sorted(allowed),'selectedOffers':offers} if allowed is not None else {}
    result['fingerprint'] = hashlib.sha256(json.dumps({**scope, 'campaign': stable_campaign, 'products': products, 'gateway': {
        'id': gateway_id, 'public': public, 'currency': currency, 'error': route_error}}, sort_keys=True).encode()).hexdigest()
    if allowed is not None:result['catalogVersion'] = 2
    return result


def quote(api, catalog, selection, shipping_id, contact):
    if catalog['blockedReason']:
        raise CatalogError(catalog['blockedReason'])
    option = next((o for o in catalog['options'] if o['key'] == selection), None)
    if not option:
        raise CatalogError('Select a billing option from this campaign and SKU')
    if option['blockedReason']:
        raise CatalogError(option['blockedReason'])
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
    data = api.call('POST', '/api/v2/order_total/calculate', body).get('data', {})
    total = money(data.get('total'))
    if option.get('dollarTest') and total != Decimal('1.00'):
        raise CatalogError('Sticky did not confirm the $1 test total; no payment submitted')
    lines = data.get('line_items', [])
    if total <= 0 or len(lines) != 1 or str(lines[0].get('id')) != str(option['productId']) or int(lines[0].get('qty', 0)) != 1:
        raise CatalogError('Sticky did not return a supported positive single-product total')
    if option.get('prepaidCycles'):
        prepaid=lines[0].get('prepaid') or {}
        if not enabled(lines[0].get('is_prepaid')) or str(prepaid.get('term'))!=str(option['prepaidCycles']) or money(prepaid.get('total'))!=money(option['upfrontPrice']) or total!=money(option['upfrontPrice']):
            raise CatalogError('Sticky prepaid total or shipment count did not match; no payment submitted')
    return {'amount': int(total * 100), 'total': str(total), 'currency': catalog['currency'],
        'selection': selection, 'shippingId': shipping_id, 'option': option,
        'campaignId': catalog['campaignId'], 'sku': catalog['sku'], 'gatewayId': catalog['gatewayId'],
        'fingerprint': catalog['fingerprint'], 'catalogVersion':catalog.get('catalogVersion',1)}
