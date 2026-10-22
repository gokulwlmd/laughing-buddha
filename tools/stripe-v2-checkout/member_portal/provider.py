"""Narrow Sticky adapter for verified, site-scoped member records.

Official contracts inspected 2026-10-23:
https://developer-prod.sticky.io/#fa3f4efb-0b1f-4467-9454-3bb1aff96aae
https://developer-prod.sticky.io/#9c2253fb-d8e2-437b-a184-4f21d0ba994c

The injected client owns authentication and transport. This adapter never logs or
returns raw order responses, searches by email, retries writes, charges cards,
changes prescriptions, or releases fulfillment. Explicit hold/reset and verified
shipping-address updates are supported. Sticky's `start` operation can
immediately bill and is excluded.
"""
from datetime import datetime
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

    def __init__(self, api, *, currency=None, clock=time.monotonic):
        self.api = api
        self.currency = currency_code(currency)
        if currency is not None and self.currency is None:
            raise ValueError('Expected a trusted three-letter currency code')
        self.clock = clock
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
            'shipping_address': {'first_name': text(raw.get('shipping_first_name'), 64),
                'last_name': text(raw.get('shipping_last_name'), 64),
                'address': text(raw.get('shipping_street_address'), 64),
                'address2': text(raw.get('shipping_street_address2'), 64),
                'city': text(raw.get('shipping_city'), 32), 'region': text(raw.get('shipping_state'), 32),
                'postal_code': text(raw.get('shipping_postcode'), 10), 'country': text(raw.get('shipping_country'), 2)}}

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
