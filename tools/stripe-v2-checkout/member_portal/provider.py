"""Narrow Sticky adapter for verified, site-scoped member records.

Official contracts inspected 2026-10-23:
https://developer-prod.sticky.io/#fa3f4efb-0b1f-4467-9454-3bb1aff96aae
https://developer-prod.sticky.io/#9c2253fb-d8e2-437b-a184-4f21d0ba994c

The injected client owns authentication and transport. This adapter never logs or
returns raw order responses, searches by email, or retries writes. Explicit
hold/reset, verified shipping-address updates, and narrowly verified included
zero-dollar prepaid cycles are supported. Sticky's `start` operation can bill
immediately and is excluded. No medical approval or fulfillment release occurs.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re
import time

US_REGIONS = frozenset('AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY AS GU MP PR VI AA AE AP'.split())
ADDRESS_FIELDS = {'first_name': ('shipping_first_name', 64), 'last_name': ('shipping_last_name', 64),
    'address': ('shipping_address1', 64), 'address2': ('shipping_address2', 64),
    'city': ('shipping_city', 32), 'region': ('shipping_state', 32),
    'postal_code': ('shipping_zip', 10), 'country': ('shipping_country', 2)}


class ProviderError(Exception):
    """A read or a locally rejected operation; messages contain no upstream data."""
    code = 'provider_unavailable'


class ProviderUncertain(ProviderError):
    """A write may have happened. Persist a hold; reconcile instead of retrying."""
    code = 'provider_outcome_unknown'


class ProviderRejected(ProviderError):
    code = 'provider_rejected'


def identifier(value, field='identifier', optional=False):
    if optional and value in (None, '', 0, '0'):
        return None
    text = str(value)
    if isinstance(value, bool) or not re.fullmatch(r'[1-9][0-9]{0,19}', text):
        raise ProviderError('Sticky returned an invalid ' + field)
    return text


def flag(value):
    if value in (True, 1, '1', 'yes', 'YES', 'true'):
        return True
    if value in (False, 0, '0', 'no', 'NO', 'false'):
        return False
    return None


def amount(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0 or result != result.quantize(Decimal('.01')):
            raise ValueError()
        return format(result, '.2f')
    except (InvalidOperation, TypeError, ValueError):
        raise ProviderError('Sticky returned an invalid monetary amount') from None


def text(value, limit=200):
    return value[:limit].strip() if isinstance(value, str) else ''


def schedule_date(value):
    if value in (None, '', '0', '0000-00-00', '00/00/0000'):
        return None
    if not isinstance(value, str):
        raise ProviderError('Sticky returned an invalid schedule date')
    for pattern in ('%Y-%m-%d', '%m/%d/%Y'):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            pass
    raise ProviderError('Sticky returned an invalid schedule date')


def currency_code(value):
    if isinstance(value, dict):
        value = value.get('code') or value.get('name')
    code = text(value, 3).upper()
    return code if re.fullmatch(r'[A-Z]{3}', code) and len(str(value).strip()) == 3 else None


def subscription_id(value):
    if value in (None, '', '0', 0):
        return None
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
        raise ProviderError('Sticky returned an invalid subscription identifier')
    return value


def clean_address(address):
    if not isinstance(address, dict) or set(address) - set(ADDRESS_FIELDS):
        raise ProviderRejected('The shipping address contains unsupported fields')
    result = {}
    for key, (_, limit) in ADDRESS_FIELDS.items():
        value = address.get(key, '' if key == 'address2' else None)
        if not isinstance(value, str) or len(value.strip()) > limit or (key != 'address2' and not value.strip()):
            raise ProviderRejected('Complete all required shipping address fields')
        if any(ord(char) < 32 for char in value):
            raise ProviderRejected('The shipping address contains invalid characters')
        result[key] = value.strip()
    result['region'] = result['region'].upper()
    result['country'] = result['country'].upper()
    if result['country'] != 'US' or result['region'] not in US_REGIONS:
        raise ProviderRejected('Use a supported US state or territory code')
    if not re.fullmatch(r'[0-9]{5}(?:-[0-9]{4})?', result['postal_code']):
        raise ProviderRejected('Use a five-digit ZIP code or ZIP+4')
    return result


def prepaid_terms(product):
    raw = product.get('prepaid')
    if raw in (None, [], {}):
        return None
    if isinstance(raw, list):
        if len(raw) != 1:
            raise ProviderError('Sticky returned ambiguous prepaid terms')
        raw = raw[0]
    if not isinstance(raw, dict):
        raise ProviderError('Sticky returned invalid prepaid terms')
    total = int(identifier(raw.get('total_cycles'), 'prepaid cycle count'))
    current = int(identifier(raw.get('current_cycle'), 'prepaid current cycle'))
    if not 1 <= current <= total <= 1000 or flag(raw.get('is_renew')) is None:
        raise ProviderError('Sticky returned invalid prepaid terms')
    return {'current_cycle': current, 'total_cycles': total, 'renews': flag(raw['is_renew'])}


def billing_model_terms(product):
    """Expose only the purchased model's explicit fixed-day schedule.

    Current master SKUs and recurring dates are not historical entitlement
    evidence. Missing/complex schedules deliberately remain unknown.
    """
    model = product.get('billing_model')
    if model is None:
        return None, None
    if not isinstance(model, dict):
        raise ProviderError('Sticky returned an invalid billing model')
    model_id = identifier(model.get('id'), 'billing model ID', optional=True)
    interval = model.get('days')
    model_type = model.get('type')
    type_id = model_type.get('id') if isinstance(model_type, dict) else model.get('type_id')
    if str(type_id) != '1' or isinstance(interval, bool) or not re.fullmatch(r'[1-9][0-9]{0,3}', str(interval)):
        return model_id, None
    return model_id, int(interval)


class StickyOrderProvider:
    supported_actions = ('pause', 'hold', 'resume')

    def __init__(self, api, *, currency=None, clock=time.monotonic, wall_clock=time.time):
        self.api = api
        self.currency = currency_code(currency)
        if currency is not None and self.currency is None:
            raise ValueError('Expected a trusted three-letter currency code')
        self.clock = clock
        # Actual UTC wall time only; the portal's Dry Run care clock must never
        # bypass a native scheduler conflict check.
        self.wall_clock = wall_clock
        self._currencies = {}

    def _call_read(self, method, path, body=None):
        try:
            result = self.api.call(method, path, body)
        except Exception:
            raise ProviderError('Sticky order information is temporarily unavailable') from None
        if not isinstance(result, dict):
            raise ProviderError('Sticky returned an invalid response')
        return result

    def _currency(self, raw, gateway_id):
        direct = currency_code(raw.get('currency')) or currency_code(raw.get('currency_code'))
        if direct:
            return direct
        if self.currency:
            return self.currency
        cached = self._currencies.get(gateway_id)
        if cached and cached[0] > self.clock():
            return cached[1]
        if not gateway_id:
            return None
        try:
            result = self._call_read('GET', '/api/v2/providers/payment/profiles/' + gateway_id)
            profile = result.get('data')
            value = currency_code(profile.get('currency')) if isinstance(profile, dict) else None
        except ProviderError:
            return None
        if value:
            self._currencies[gateway_id] = (self.clock() + 300, value)
        return value

    def read_order(self, order_id, *, expected_campaign=None, expected_customer_id=None):
        requested = identifier(order_id, 'requested order ID')
        raw = self._call_read('POST', '/api/v1/order_view', {'order_id': [requested], 'includes': ['has_been_posted']})
        if str(raw.get('response_code')) != '100':
            raise ProviderError('Sticky could not verify this order')
        envelope_code = raw['response_code']
        if 'data' in raw:
            data = raw['data']
            if not isinstance(data, dict) or requested not in data or len(data) != 1:
                raise ProviderError('Sticky returned an unexpected order collection')
            raw = data[requested]
        if not isinstance(raw, dict) or str(raw.get('response_code', envelope_code)) != '100':
            raise ProviderError('Sticky could not verify this order')
        actual_id = identifier(raw.get('order_id'), 'order ID')
        campaign = identifier(raw.get('campaign_id'), 'campaign ID')
        customer_id = identifier(raw.get('customer_id'), 'customer ID')
        if actual_id != requested:
            raise ProviderError('Sticky returned a different order')
        if expected_campaign is not None and campaign != identifier(expected_campaign):
            raise ProviderRejected('This order does not belong to the expected site')
        if expected_customer_id is not None and customer_id != identifier(expected_customer_id):
            raise ProviderRejected('This order does not belong to the expected customer')
        gateway = identifier(raw.get('gateway_id'), 'gateway ID', optional=True)
        products = raw.get('products')
        if not isinstance(products, list) or not 1 <= len(products) <= 100:
            raise ProviderError('Sticky returned invalid order products')
        result_products = []
        for product in products:
            if not isinstance(product, dict):
                raise ProviderError('Sticky returned invalid order products')
            pid = identifier(product.get('product_id'), 'product ID')
            sku = text(product.get('sku'), 128)
            if not sku:
                raise ProviderError('Sticky returned a product without a SKU')
            sid = subscription_id(product.get('subscription_id'))
            recurring = flag(product.get('is_recurring'))
            held = flag(product.get('on_hold'))
            cycle_date = schedule_date(product.get('recurring_date'))
            prepaid = prepaid_terms(product)
            model_id, interval_days = billing_model_terms(product)
            offer = product.get('offer')
            if offer is not None and not isinstance(offer, dict):
                raise ProviderError('Sticky returned an invalid order offer')
            offer_id = identifier((offer or {}).get('id'), 'offer ID', optional=True)
            if held is True:
                billing = 'held'
            elif recurring is True:
                billing = 'active'
            elif recurring is False:
                billing = ('completed' if prepaid and not prepaid['renews']
                           and prepaid['current_cycle'] == prepaid['total_cycles'] else 'inactive')
            else:
                billing = 'unknown'
            # Recurring dates are cycle dates. Intermediate prepaid cycles may
            # create zero-dollar shipment orders instead of another full charge.
            bill_date = cycle_date if not prepaid or (prepaid['renews'] and prepaid['current_cycle'] == prepaid['total_cycles']) else None
            quantity = int(identifier(product.get('product_qty', product.get('quantity')), 'product quantity'))
            if quantity > 10000:
                raise ProviderError('Sticky returned an invalid product quantity')
            result_products.append({'product_id': pid, 'sku': sku, 'name': text(product.get('name')) or sku,
                'subscription_id': sid, 'is_recurring': recurring, 'on_hold': held,
                'billing_status': billing, 'next_billing_date': bill_date, 'next_cycle_date': cycle_date,
                'quantity': quantity, 'prepaid': prepaid, 'is_shippable': flag(product.get('is_shippable')),
                'billing_model_id': model_id, 'billing_interval_days': interval_days,
                'offer_id': offer_id,
                'stop_after_next_cycle': flag(product.get('is_terminal'))})
        order_status = str(raw.get('order_status', ''))
        payment = {'1': 'initiated', '2': 'paid', '6': 'void_or_refunded', '7': 'declined',
                   '8': 'paid', '10': 'awaiting', '11': 'pending'}.get(order_status, 'unknown')
        total = amount(raw.get('order_total'))
        if flag(raw.get('is_chargeback')) is True:
            payment = 'chargeback'
        elif flag(raw.get('is_void')) is True:
            payment = 'voided'
        elif flag(raw.get('is_refund')) is True:
            refund = raw.get('amount_refunded_to_date', raw.get('refund_amount'))
            payment = 'refunded' if refund is not None and Decimal(amount(refund)) >= Decimal(total) else 'partially_refunded'
        shippable = flag(raw.get('shippable'))
        shipping = ('not_shippable' if shippable is False else 'shipped' if order_status == '8'
                    else 'on_hold' if flag(raw.get('on_hold')) is True else 'unknown')
        child_ids = raw.get('child_id', '')
        if isinstance(child_ids, str):
            child_ids = [value.strip() for value in child_ids.split(',') if value.strip() not in ('', '0')]
        elif child_ids in (None, 0):
            child_ids = []
        if not isinstance(child_ids, list) or len(child_ids) > 1000:
            raise ProviderError('Sticky returned invalid child order references')
        posted = raw.get('has_been_posted')
        posted = int(posted) if str(posted) in ('0', '1', '2') else None
        return {'id': actual_id, 'campaign_id': campaign, 'customer_id': customer_id,
            'contact_id': identifier(raw.get('contact_id'), 'contact ID', optional=True),
            'customer': {'name': ' '.join(filter(None, [text(raw.get('first_name'), 64), text(raw.get('last_name'), 64)])),
                         'email': text(raw.get('email_address'), 254)},
            'products': result_products, 'payment_status': payment, 'fulfillment_status': shipping,
            'total': total, 'currency': self._currency(raw, gateway), 'created_at': text(raw.get('time_stamp'), 32) or None,
            'order_status': order_status if order_status.isdigit() else 'unknown', 'gateway_id': gateway,
            'test_order': flag(raw.get('is_test_cc')), 'ancestor_id': identifier(raw.get('ancestor_id'), optional=True),
            'parent_id': identifier(raw.get('parent_id'), optional=True),
            'child_ids': [identifier(value, 'child order ID') for value in child_ids],
            # Official order_view uses this literal for an unshipped order.
            # It is not a valid recurring date and must not relax that parser.
            'shipping_date': None if raw.get('shipping_date') == 'Not Shipped' else schedule_date(raw.get('shipping_date')),
            'tracking_number': text(raw.get('tracking_number'), 150) or None,
            'fulfillment_posted': posted,
            'shipping_id': identifier(raw.get('shipping_id'), 'shipping ID', optional=True),
            'shipping_amount': amount(raw['shipping_amount']) if raw.get('shipping_amount') is not None else None,
            'tax_amount': amount(raw['order_sales_tax_amount']) if raw.get('order_sales_tax_amount') is not None else None,
            'shipping_address': {'first_name': text(raw.get('shipping_first_name'), 64),
                'last_name': text(raw.get('shipping_last_name'), 64),
                'address': text(raw.get('shipping_street_address'), 64),
                'address2': text(raw.get('shipping_street_address2'), 64),
                'city': text(raw.get('shipping_city'), 32), 'region': text(raw.get('shipping_state'), 32),
                'postal_code': text(raw.get('shipping_postcode'), 10), 'country': text(raw.get('shipping_country'), 2)}}

    def _included_context(self, order_id, *, expected_campaign, expected_customer_id,
            expected_subscription_id, expected_product_id, expected_offer_id,
            expected_billing_model_id, term_order_id, term_started_at,
            shipment_interval_days, shipment_count, target_cycle, _allow_child=False):
        """Read and prove the actual paid term and its contiguous native chain."""
        if (any(type(n) is not int for n in (shipment_interval_days, shipment_count, target_cycle))
                or not 2 <= target_cycle <= shipment_count <= 36
                or not 1 <= shipment_interval_days <= 730
                or shipment_interval_days * shipment_count > 730):
            raise ProviderRejected('Only an included cycle within a verified prepaid term can be claimed')
        scope = {'expected_campaign': identifier(expected_campaign), 'expected_customer_id': identifier(expected_customer_id)}
        term_id, requested = identifier(term_order_id), identifier(order_id)
        expected = {'product_id': identifier(expected_product_id), 'offer_id': identifier(expected_offer_id),
                    'billing_model_id': identifier(expected_billing_model_id), 'subscription_id': subscription_id(expected_subscription_id)}
        if not expected['subscription_id']:
            raise ProviderRejected('A verified subscription is required')
        with ThreadPoolExecutor(max_workers=2) as pool:
            original_future = pool.submit(self.read_order, term_id, **scope)
            source_future = pool.submit(self.read_order, requested, **scope) if requested != term_id else original_future
            original, source = original_future.result(), source_future.result()
        def purchase_date(value):
            for fmt in ('%Y-%m-%d %H:%M:%S', '%m/%d/%Y %H:%M:%S', '%Y-%m-%d', '%m/%d/%Y', '%Y-%m-%dT%H:%M:%SZ'):
                try: return datetime.strptime(value or '', fmt).date()
                except (ValueError, TypeError): pass
            raise ProviderRejected('The original paid term date could not be verified')
        start = purchase_date(original['created_at'])
        if start != purchase_date(term_started_at) or Decimal(original['total']) <= 0:
            raise ProviderRejected('The original paid term could not be verified')
        if len(original['products']) != 1 or not original['products'][0]['prepaid']:
            raise ProviderRejected('A single prepaid product is required')
        root_id = original['ancestor_id'] or original['id']
        original_line = original['products'][0]
        renews = original_line['prepaid']['renews']
        def check_order(order, cycle):
            if (order['payment_status'] != 'paid' or len(order['products']) != 1
                    or not original['currency'] or order['currency'] != original['currency']
                    or (order['ancestor_id'] or order['id']) != root_id
                    or order['gateway_id'] != original['gateway_id']
                    or order['test_order'] is not original['test_order']):
                raise ProviderRejected('The order does not establish this paid subscription term')
            line = order['products'][0]
            if (any(line[k] != v for k, v in expected.items()) or line['sku'] != original_line['sku']
                    or line['quantity'] != 1 or line['is_shippable'] is not False
                    or line['prepaid'] != {'current_cycle': cycle, 'total_cycles': shipment_count, 'renews': renews}
                    or order['shipping_amount'] != '0.00' or order['tax_amount'] != '0.00'
                    or order['fulfillment_status'] != 'not_shippable'
                    or order['shipping_date'] or order['tracking_number']
                    or order['fulfillment_posted'] != 0
                    or (cycle > 1 and order['shipping_id'] not in (None, original['shipping_id']))
                    or (cycle > 1 and order['total'] != '0.00')):
                raise ProviderRejected('Only an isolated, included zero-dollar prepaid cycle is supported')
        check_order(original, 1)
        current, cycle, seen = source, target_cycle - 1, set()
        if _allow_child and source['child_ids']:
            if len(source['child_ids']) != 1:
                raise ProviderRejected('The native child order needs reconciliation')
            child = self.read_order(source['child_ids'][0], **scope)
            check_order(child, target_cycle)
            if child['parent_id'] != source['id'] or child['child_ids']:
                raise ProviderRejected('The native child order lineage is ambiguous')
            seen.add(child['id'])
        while True:
            check_order(current, cycle)
            if current['id'] == term_id:
                if cycle != 1: raise ProviderRejected('The cycle is outside the original paid term')
                break
            if cycle <= 1 or current['id'] in seen or not current['parent_id'] or current['parent_id'] == current['id']:
                raise ProviderRejected('The native subscription lineage needs reconciliation')
            seen.add(current['id'])
            previous = self.read_order(current['parent_id'], **scope)
            descendants = previous['child_ids']
            # Sticky may list either the immediate child or every descendant.
            # Only the exact chain already verified below this parent counts;
            # duplicate IDs, missing links and unrelated branches stay blocked.
            if (len(descendants) != len(set(descendants))
                    or (descendants != [current['id']] and set(descendants) != seen)):
                raise ProviderRejected('The native subscription lineage is ambiguous')
            current, cycle = previous, cycle - 1
        next_date = (start + timedelta(days=(target_cycle - 1) * shipment_interval_days)).isoformat()
        following = (start + timedelta(days=target_cycle * shipment_interval_days)).isoformat() if target_cycle < shipment_count or renews else None
        return {'source': source, 'original': original, 'scope': scope, 'expected': expected,
                'start': start, 'next_date': next_date, 'following': following, 'renews': renews,
                'check_order': check_order, 'target_cycle': target_cycle, 'shipment_count': shipment_count,
                'interval': shipment_interval_days}

    def _included_capability(self, context):
        source, original = context['source'], context['original']
        line = source['products'][0]
        today = datetime.fromtimestamp(self.wall_clock(), timezone.utc).date().isoformat()
        if (source['child_ids'] or line['billing_status'] != 'active' or line['stop_after_next_cycle'] is not False
                or line['next_cycle_date'] != context['next_date'] or context['next_date'] <= today):
            raise ProviderRejected('The scheduled cycle needs reconciliation before an early claim')
        # Sticky can omit shipping_id on its own later $0 prepaid children.
        # The verified contiguous chain supplies the original profile, which
        # must still be fetched fresh and prove free recurring shipping. A
        # different explicit child profile never inherits this exception.
        shipping_id = original['shipping_id']
        if (not shipping_id or source['shipping_id'] not in (None, shipping_id) or not source['gateway_id']
                or (source['shipping_id'] is None and (context['target_cycle'] <= 2 or source['total'] != '0.00'))):
            raise ProviderRejected('The shipping and gateway configuration must be verified')
        paths = {'campaign': '/api/v2/campaigns/' + source['campaign_id'],
                 'product': '/api/v2/products/' + line['product_id'],
                 'offer': '/api/v2/offers/' + line['offer_id'],
                 'model': '/api/v2/billing_models/' + line['billing_model_id'],
                 'gateway': '/api/v2/providers/payment/profiles/' + source['gateway_id'],
                 'shipping': '/api/v2/shipping/' + shipping_id}
        # Sticky.call creates independent urllib openers. All these fresh reads
        # are independent; writes below remain strictly sequential.
        with ThreadPoolExecutor(max_workers=len(paths)) as pool:
            pending = {name: pool.submit(self._call_read, 'GET', path) for name, path in paths.items()}
            values = {name: task.result() for name, task in pending.items()}
        data = {}
        for name, response in values.items():
            value = response.get('data')
            if response.get('status') != 'SUCCESS' or not isinstance(value, dict):
                raise ProviderError('Sticky could not verify included-cycle configuration')
            data[name] = value
        campaign, product, offer, model, gateway, shipping = (data[k] for k in paths)
        ids = [(campaign.get('id', campaign.get('c_id')), source['campaign_id']),
               (product.get('id'), line['product_id']), (offer.get('id'), line['offer_id']),
               (model.get('id'), line['billing_model_id']), (gateway.get('id'), source['gateway_id']),
               (shipping.get('id'), shipping_id)]
        if any(identifier(actual) != expected for actual, expected in ids):
            raise ProviderRejected('The included-cycle configuration changed')
        integrations = ('fulfillment_id', 'tax_provider_id', 'email_provider_id', 'membership_provider_id', 'postback_profiles')
        if (flag(product.get('is_shippable')) is not False or flag(product.get('taxable', product.get('is_taxable'))) is not False
                or product.get('sku') != line['sku'] or flag(campaign.get('is_active')) is not True
                or flag(campaign.get('is_archived')) is not False
                or any(campaign.get(k) not in (None, 0, '0', []) for k in integrations)
                or amount(shipping.get('amount_recurring')) != '0.00'
                or any(shipping.get(key) is not None and amount(shipping[key]) != '0.00'
                       for key in ('threshold_amount', 'threshold_charge_amount'))):
            raise ProviderRejected('Claims require a non-shippable, non-taxable campaign without external integrations or recurring shipping fees')
        from prepaid import cycles_for, renewal_for
        try:
            configured_cycles, configured_renewal = cycles_for(offer), renewal_for(offer)
        except (ValueError, TypeError, KeyError, InvalidOperation):
            raise ProviderRejected('The purchased prepaid configuration is incomplete') from None
        if (billing_model_terms({'billing_model': model}) != (line['billing_model_id'], context['interval'])
                or model.get('expire_cycles') not in (None, 0, '0') or model.get('buffer_days') not in (None, 0, '0')
                or flag(model.get('is_archived')) is True
                or configured_cycles != context['shipment_count'] or configured_renewal != context['renews']
                or flag(offer.get('is_archived')) is True
                or not any(str(p.get('id')) == line['product_id'] for p in offer.get('products', []) if isinstance(p, dict))
                or not any(str(m.get('id')) == line['billing_model_id'] for m in (offer.get('offer_billing_models') or offer.get('billing_models') or []) if isinstance(m, dict))
                or not any(str(o.get('id')) == line['offer_id'] for o in campaign.get('offers', []) if isinstance(o, dict))):
            raise ProviderRejected('The purchased prepaid schedule no longer matches its configuration')
        if source['test_order'] is True:
            if source['gateway_id'] != '1' or str(gateway.get('account_id')) != '10' or gateway.get('account_name') != 'Dry Run Testing':
                raise ProviderRejected('The Dry Run gateway identity could not be verified')
        elif source['test_order'] is False:
            routes = [str(campaign.get('gateway_id'))] + [str(p.get('provider', {}).get('id')) for p in campaign.get('alternative_payments', []) if isinstance(p, dict)]
            if str(gateway.get('account_id')) != '250' or source['gateway_id'] not in routes:
                raise ProviderRejected('The existing Stripe Connect v2 route could not be verified')
        else:
            raise ProviderRejected('The payment routing mode is unknown')
        return {'available': True, 'source_order_id': source['id'], 'term_order_id': original['id'],
                'subscription_id': line['subscription_id'], 'target_cycle': context['target_cycle'],
                'amount': '0.00', 'currency': source['currency'], 'next_cycle_date': context['next_date'],
                'following_cycle_date': context['following'], 'mode': 'isolated_nonshippable'}

    def included_cycle_capability(self, order_id, **scope):
        """Fresh read-only capability proof; never call from a task-list render."""
        return self._included_capability(self._included_context(order_id, **scope))

    def _included_child(self, context, child_order_id=None, *, anchored=True):
        parent = self.read_order(context['source']['id'], **context['scope'])
        context['check_order'](parent, context['target_cycle'] - 1)
        if not parent['child_ids']:
            if child_order_id: raise ProviderRejected('The returned order is not a verified native child')
            return None
        if len(parent['child_ids']) != 1 or (child_order_id and parent['child_ids'][0] != identifier(child_order_id)):
            raise ProviderRejected('The native child order needs reconciliation')
        child = self.read_order(parent['child_ids'][0], **context['scope'])
        context['check_order'](child, context['target_cycle'])
        line = child['products'][0]
        if child['parent_id'] != parent['id'] or child['child_ids']:
            raise ProviderRejected('The native child order lineage is ambiguous')
        if context['following'] is None:
            valid = line['billing_status'] == 'completed' and line['is_recurring'] is False and line['next_cycle_date'] is None
        else:
            valid = line['billing_status'] == 'active' and line['is_recurring'] is True
            if anchored: valid = valid and line['next_cycle_date'] == context['following']
        if not valid:
            raise ProviderRejected('The next native cycle date needs reconciliation')
        return child

    def reconcile_included_cycle(self, order_id, *, child_order_id=None, **scope):
        """Read only. An absent child is not permission to repeat an uncertain write."""
        return self._included_child(self._included_context(order_id, _allow_child=True, **scope), child_order_id)

    def advance_included_cycle(self, order_id, **scope):
        """One native included-cycle attempt, then verify and restore its anchor.

        Callers own a durable per-term/cycle claim journal. Neither a timeout nor
        an unconfirmed date update authorizes another force-bill attempt.
        https://developer-prod.sticky.io/#efdf6132-ff70-4f17-8ce4-40d6ab81af43
        """
        context = self._included_context(order_id, **scope)
        self._included_capability(context)
        source = context['source']
        # Recheck the latest source after the parallel catalog reads, before the
        # one write. Refuse on/after actual UTC due day; no scheduler race claim.
        fresh = self.read_order(source['id'], **context['scope'])
        if fresh != source or context['next_date'] <= datetime.fromtimestamp(self.wall_clock(), timezone.utc).date().isoformat():
            raise ProviderRejected('The scheduled order changed during claim preparation')
        payload = {'order_id': source['id'], 'product_id': context['expected']['product_id']}
        if source['test_order']:
            payload.update(forceGatewayId=1, preserve_force_gateway=1)
        try:
            result = self.api.call('POST', '/api/v1/order_force_bill', payload)
            if not isinstance(result, dict) or str(result.get('response_code')) != '100' or str(result.get('error_found')) != '0':
                raise ProviderUncertain('Sticky did not confirm the included cycle')
            child_id = identifier(result.get('new_order_id') or result.get('order_id'))
            child = self._included_child(context, child_id, anchored=False)
            if context['following'] and child['products'][0]['next_cycle_date'] != context['following']:
                result = self.api.call('POST', '/api/v1/subscription_order_update', {
                    'order_id': child['id'], 'product_id': context['expected']['product_id'],
                    'new_recurring_date': datetime.strptime(context['following'], '%Y-%m-%d').strftime('%m/%d/%Y')})
                nested = result.get('new_recurring_date', {}) if isinstance(result, dict) else {}
                if (not isinstance(result, dict) or str(result.get('response_code')) != '100'
                        or (nested and (not isinstance(nested, dict) or str(nested.get('response_code')) != '100'))):
                    raise ProviderUncertain('The included cycle exists but its next date is unconfirmed')
            return self._included_child(context, child_id, anchored=True)
        except Exception:
            raise ProviderUncertain('The included cycle may exist. Reconcile its order and schedule before any further attempt') from None

    def subscription_action(self, order_id, subscription_id, action, *, expected_campaign, expected_customer_id):
        """Apply exactly one documented hold/reset and confirm by a fresh read.

        `resume` restores the saved cycle date, which may already be due. It is
        not a promise that a future scheduler charge cannot happen immediately.
        Callers must verify membership, consent, and durable idempotency first.
        """
        if action not in self.supported_actions:
            raise ProviderRejected('This subscription action is not supported')
        expected_campaign = identifier(expected_campaign, 'expected campaign ID')
        expected_customer_id = identifier(expected_customer_id, 'expected customer ID')
        before = self.read_order(order_id, expected_campaign=expected_campaign, expected_customer_id=expected_customer_id)
        matches = [p for p in before['products'] if p['subscription_id'] == subscription_id and subscription_id]
        if len(matches) != 1:
            raise ProviderRejected('The requested subscription is not on this order')
        product = matches[0]
        if sum(p['product_id'] == product['product_id'] for p in before['products']) != 1:
            raise ProviderRejected('This order needs staff review before changing its subscription')
        desired = 'active' if action == 'resume' else 'held'
        if product['billing_status'] == desired:
            return before
        if product['billing_status'] not in ('active', 'held') or before['order_status'] not in ('2', '8', '9'):
            raise ProviderRejected('This subscription cannot be changed through the portal')
        if action == 'resume' and not product['next_cycle_date']:
            raise ProviderRejected('A scheduled cycle date is required before resuming')
        payload = {'order_id': before['id'], 'product_id': product['product_id'],
                   'status': 'reset' if action == 'resume' else 'stop'}
        try:
            response = self.api.call('POST', '/api/v1/subscription_order_update', payload)
        except Exception:
            raise ProviderUncertain('The subscription change needs reconciliation before another attempt') from None
        # Even a refusal can have partial effects. Never retry or claim success
        # based solely on HTTP status or a generic upstream response string.
        if not isinstance(response, dict) or str(response.get('response_code')) != '100':
            raise ProviderUncertain('Sticky did not confirm the complete subscription change')
        try:
            after = self.read_order(order_id, expected_campaign=before['campaign_id'], expected_customer_id=before['customer_id'])
        except ProviderError:
            raise ProviderUncertain('The subscription change was sent but its result could not be verified') from None
        verified = [p for p in after['products'] if p['subscription_id'] == subscription_id and p['product_id'] == product['product_id']]
        if len(verified) != 1 or verified[0]['billing_status'] != desired:
            raise ProviderUncertain('The subscription change needs reconciliation before another attempt')
        return after

    def update_address(self, order_id, address, *, expected_campaign, expected_customer_id):
        """Update only this unposted, unshipped order's shipping fields.

        This does not change billing addresses, recall a parcel, update a medical
        team, or promise propagation to existing/future subscription orders.
        Official order_update contract:
        https://developer-prod.sticky.io/#50bf0f66-38b2-4513-908d-04f4af02593f
        """
        desired = clean_address(address)
        expected_campaign = identifier(expected_campaign, 'expected campaign ID')
        expected_customer_id = identifier(expected_customer_id, 'expected customer ID')
        before = self.read_order(order_id, expected_campaign=expected_campaign, expected_customer_id=expected_customer_id)
        if (before['order_status'] not in ('1', '2', '9', '10', '11') or before['tracking_number']
                or before['shipping_date'] or before['child_ids'] or before['fulfillment_posted'] != 0):
            raise ProviderRejected('This order needs staff review before its shipping address can change')
        if before['shipping_address'] == desired:
            return before
        payload = {'order_id': {before['id']: {ADDRESS_FIELDS[key][0]: value for key, value in desired.items()}}}
        try:
            response = self.api.call('POST', '/api/v1/order_update', payload)
        except Exception:
            raise ProviderUncertain('The address change needs reconciliation before another attempt') from None
        if not isinstance(response, dict) or str(response.get('response_code')) != '100':
            raise ProviderUncertain('Sticky did not confirm the complete shipping address change')
        try:
            after = self.read_order(order_id, expected_campaign=expected_campaign, expected_customer_id=expected_customer_id)
        except ProviderError:
            raise ProviderUncertain('The address change was sent but its result could not be verified') from None
        if (after['shipping_address'] != desired or after['tracking_number'] or after['shipping_date']
                or after['fulfillment_posted'] != 0 or after['child_ids']):
            raise ProviderUncertain('The address change needs reconciliation before another attempt')
        return after

    def _owned_subscription(self, order, sid):
        sid = subscription_id(sid)
        lines = [p for p in order['products'] if p['subscription_id'] == sid and sid]
        if len(lines) != 1 or not order.get('contact_id'):
            raise ProviderRejected('This subscription requires verified customer ownership')
        raw = self._call_read('GET', '/api/v2/subscriptions/' + sid)
        record = raw.get('data')
        if raw.get('status') != 'SUCCESS' or not isinstance(record, dict):
            raise ProviderError('Sticky could not verify the subscription')
        if (record.get('id') != sid or identifier(record.get('contact_id'), 'subscription contact ID') != order['contact_id']
                or not isinstance(record.get('product'), dict)
                or identifier(record['product'].get('id'), 'subscription product ID') != lines[0]['product_id']):
            raise ProviderRejected('The subscription does not match the verified order')
        shipping = record.get('shipping')
        if not isinstance(shipping, dict):
            raise ProviderError('Sticky did not provide the subscription shipping address')
        country = shipping.get('country_iso2') or shipping.get('country2') or shipping.get('country')
        address = {'first_name': text(shipping.get('first_name'), 64), 'last_name': text(shipping.get('last_name'), 64),
            'address': text(shipping.get('address'), 64), 'address2': text(shipping.get('address2'), 64),
            'city': text(shipping.get('city'), 32), 'region': text(shipping.get('state'), 32),
            'postal_code': text(shipping.get('zip'), 10), 'country': text(country, 64)}
        return lines[0], record, address

    def update_subscription_address(self, order_id, subscription_id, address, *, expected_campaign, expected_customer_id):
        """Set the documented future subscription address override, not an order.

        https://developer-v2.sticky.io/#cf47637e-e019-4e31-ba4b-58416e4089e6
        The documented payload does not establish recipient-name or address2
        updates. Those changes require staff review rather than silent omission.
        """
        desired = clean_address(address)
        expected_campaign = identifier(expected_campaign, 'expected campaign ID')
        expected_customer_id = identifier(expected_customer_id, 'expected customer ID')
        before = self.read_order(order_id, expected_campaign=expected_campaign, expected_customer_id=expected_customer_id)
        product, record, current = self._owned_subscription(before, subscription_id)
        if record.get('status') not in ('active', 'paused', 'retrying', 'cancelled'):
            raise ProviderRejected('The subscription status needs review before changing its address')
        if any(desired[key] != current[key] for key in ('first_name', 'last_name', 'address2')):
            raise ProviderRejected('Recipient name and apartment changes need staff review for subscriptions')
        if desired != current:
            payload = {'street': desired['address'], 'city': desired['city'], 'state': desired['region'],
                       'zip': desired['postal_code'], 'country': desired['country']}
            try:
                response = self.api.call('POST', '/api/v2/subscriptions/' + product['subscription_id'] + '/override/address', payload)
            except Exception:
                raise ProviderUncertain('The subscription address change needs reconciliation before another attempt') from None
            if not isinstance(response, dict) or response.get('status') != 'SUCCESS':
                raise ProviderUncertain('Sticky did not confirm the subscription address change')
            try:
                after = self.read_order(order_id, expected_campaign=expected_campaign, expected_customer_id=expected_customer_id)
                _, _, current = self._owned_subscription(after, subscription_id)
            except ProviderError:
                raise ProviderUncertain('The subscription address was sent but its result could not be verified') from None
            if current != desired:
                raise ProviderUncertain('The subscription address change needs reconciliation before another attempt')
        else:
            after = before
        # Keep the order address and the subscription override distinct. Existing
        # shipments are not rerouted or updated by setting a future override.
        for item in after['products']:
            if item['subscription_id'] == subscription_id:
                item['subscription_shipping_address'] = current
        return after

    def read_subscription_address(self, order_id, subscription_id, *, expected_campaign, expected_customer_id):
        """Read the verified future override without assuming the order address."""
        order = self.read_order(order_id, expected_campaign=identifier(expected_campaign),
                                expected_customer_id=identifier(expected_customer_id))
        _, _, address = self._owned_subscription(order, subscription_id)
        return address

    def verify_care_schedule(self, order_id, *, expected_campaign, expected_customer_id,
                             shipment_interval_days, shipment_count, term_days):
        """Verify an imported original prepaid term, using reads only.

        Current model/offer metadata alone is insufficient: the original paid
        order must itself record the prepaid count, first cycle, exact IDs and
        a first scheduled cycle consistent with the original purchase date.
        Ambiguous historical or already-advanced records need staff review.
        """
        if (any(type(n) is not int for n in (shipment_interval_days, shipment_count, term_days))
                or not 1 <= shipment_interval_days <= 730 or not 2 <= shipment_count <= 36
                or term_days != shipment_interval_days * shipment_count):
            raise ProviderRejected('Use a complete fixed prepaid shipment schedule')
        order = self.read_order(order_id, expected_campaign=identifier(expected_campaign),
                                expected_customer_id=identifier(expected_customer_id))
        if (order['payment_status'] != 'paid' or Decimal(order['total']) <= 0 or len(order['products']) != 1
                or order['parent_id'] not in (None, order['id']) or order['child_ids']
                or order['ancestor_id'] not in (None, order['id'])):
            raise ProviderRejected('Verify the original paid term before assigning its care schedule')
        product = order['products'][0]
        prepaid = product['prepaid']
        if (not prepaid or prepaid['current_cycle'] != 1 or prepaid['total_cycles'] != shipment_count
                or not product['offer_id'] or not product['billing_model_id'] or not product['subscription_id']
                or product['billing_status'] != 'active' or not product['next_cycle_date']):
            raise ProviderRejected('The original order does not establish the requested prepaid schedule')
        created = None
        for fmt in ('%Y-%m-%d %H:%M:%S', '%m/%d/%Y %H:%M:%S', '%Y-%m-%d', '%m/%d/%Y'):
            try:
                created = datetime.strptime(order['created_at'] or '', fmt).date()
                break
            except ValueError:
                pass
        if created is None or product['next_cycle_date'] != (created + timedelta(days=shipment_interval_days)).isoformat():
            raise ProviderRejected('The original purchase and next cycle do not confirm this interval')
        raw = self._call_read('GET', '/api/v2/billing_models/' + product['billing_model_id'])
        model = raw.get('data')
        if (raw.get('status') != 'SUCCESS' or not isinstance(model, dict)
                or identifier(model.get('id'), 'billing model ID') != product['billing_model_id']):
            raise ProviderError('Sticky could not verify the purchased billing model')
        _, days = billing_model_terms({'billing_model': model})
        if (days != shipment_interval_days or model.get('expire_cycles') not in (None, 0, '0')
                or model.get('buffer_days') not in (None, 0, '0') or flag(model.get('is_archived')) is True):
            raise ProviderRejected('The purchased model does not confirm the requested fixed interval')
        raw = self._call_read('GET', '/api/v2/offers/' + product['offer_id'])
        offer = raw.get('data')
        if (raw.get('status') != 'SUCCESS' or not isinstance(offer, dict)
                or identifier(offer.get('id'), 'offer ID') != product['offer_id']):
            raise ProviderError('Sticky could not verify the purchased offer')
        from prepaid import cycles_for, renewal_for
        try:
            offer_cycles, offer_renews = cycles_for(offer), renewal_for(offer)
        except (ValueError, TypeError, KeyError, InvalidOperation):
            raise ProviderRejected('The purchased offer needs schedule review') from None
        models = offer.get('offer_billing_models') or offer.get('billing_models') or []
        products = offer.get('products') or []
        if (offer_cycles != shipment_count or offer_renews != prepaid['renews']
                or flag(offer.get('is_archived')) is True
                or not any(isinstance(p, dict) and str(p.get('id')) == product['product_id'] for p in products)
                or not any(isinstance(m, dict) and str(m.get('id')) == product['billing_model_id'] for m in models)):
            raise ProviderRejected('The purchased offer no longer confirms the original entitlement')
        return {'product_id': product['product_id'], 'offer_id': product['offer_id'],
            'billing_model_id': product['billing_model_id'], 'subscription_id': product['subscription_id'],
            'shipment_interval_days': shipment_interval_days, 'shipment_count': shipment_count,
            'term_days': term_days, 'term_started_at': order['created_at'], 'term_order_id': order['id'],
            'prepaid_renews': prepaid['renews'], 'upfront_total': order['total'], 'currency': order['currency'],
            'evidence_source': 'original_order_prepaid_and_cycle_date_verified_against_purchased_offer_model'}
