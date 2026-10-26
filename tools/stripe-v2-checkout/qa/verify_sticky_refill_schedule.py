"""Opt-in, journaled provider verification; never run as automated CI.

Run on the existing Fly host only after explicit Dry Run approval. Two new
non-shippable products and two custom prepaid offers are isolated in a new
campaign. Eight synthetic orders prove 2/4-cycle terms through their renewal.
No production products, offers, subscriptions or campaign assignments change.
"""
import hashlib
import json
import os
from decimal import Decimal
from pathlib import Path

RUN = 'refill-sku-contract-20261026-v1'
INTEGRATIONS = ('fulfillment_id', 'email_provider_id', 'membership_provider_id',
                'tax_provider_id', 'postback_profiles', 'alternative_payments')


def offer_body(initial, refill, count):
    if count not in (2, 4) or initial == refill:
        raise ValueError('Use two distinct products and a two/four-delivery term')
    return {'name': f'{RUN} / {count} deliveries', 'type_id': 2, 'is_trial': 0,
            'products': [{'id': initial}], 'billing_models': [{'id': 4}],
            'recurring': {'cycle_type_id': 2, 'terminating_cycle_type_id': 2,
                          'products': [{'id': refill, 'cycle_depth': 1}]},
            'prepaid': {'is_subscription': 1, 'is_convert_to_standard': 0,
                        'is_cancel_immediate': 0, 'is_refund_allowed': 1,
                        'is_initial_shipping_on_restart': 0,
                        'is_prepaid_notification_enabled': 0,
                        'terms': [{'cycles': count, 'discount_type_id': 1, 'discount_value': 0}]}}


class Verification:
    def __init__(self, api, journal):
        self.api, self.path = api, Path(journal)
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {'run': RUN, 'operations': {}}
        if self.state['run'] != RUN:
            raise ValueError('Wrong verification journal')

    def save(self):
        temporary = self.path.with_suffix('.tmp')
        with temporary.open('w') as f:
            os.chmod(temporary, 0o600)
            json.dump(self.state, f, sort_keys=True)
            f.flush(); os.fsync(f.fileno())
        temporary.replace(self.path)

    def write(self, key, path, body):
        digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        previous = self.state['operations'].get(key)
        if previous:
            if previous['digest'] != digest or previous['status'] != 'confirmed':
                raise ValueError('Reconcile uncertain or changed operation: ' + key)
            return previous['result']
        self.state['operations'][key] = {'digest': digest, 'status': 'pending', 'path': path}
        self.save()
        response = self.api.call('POST', path, body)
        # Never store full provider responses, auth data or request bodies.
        result = {k: response[k] for k in ('status', 'response_code', 'error_found', 'order_id', 'new_order_id', 'test') if k in response}
        if isinstance(response.get('data'), dict):
            result['data'] = {k: response['data'][k] for k in ('id', 'c_id') if k in response['data']}
        self.state['operations'][key].update(status='confirmed', result=result)
        self.save()
        if path.startswith('/api/v2/') and response.get('status') != 'SUCCESS':
            raise ValueError('Provider rejected configuration: ' + key)
        return result

    def create(self, key, path, body):
        result = self.write(key, path, body)
        if result.get('status') != 'SUCCESS':
            raise ValueError('Configuration was not confirmed: ' + key)
        return int(result['data'].get('id') or result['data']['c_id'])

    def setup(self):
        gateway = self.api.detail('/api/v2/providers/payment/profiles/1')
        if gateway.get('account_id') != 10 or gateway.get('account_name') != 'Dry Run Testing':
            raise ValueError('Gateway 1 is not the verified Dry Run provider')
        model = self.api.detail('/api/v2/billing_models/4')
        shipping = self.api.detail('/api/v2/shipping/2')
        if model.get('days') != 90 or any(Decimal(str(shipping.get(k, -1))) != 0 for k in ('amount_trial', 'amount_recurring')):
            raise ValueError('90-day billing and free shipping need verification')
        ids = []
        for role in ('INITIAL', 'REFILL'):
            sku = RUN + '-' + role
            body = {'name': sku, 'sku': sku, 'category_id': 113, 'price': 10,
                    'description': 'Isolated synthetic verification; no medication or fulfillment.',
                    'cost_of_goods': 0, 'restocking_fee': 0, 'max_quantity': 1,
                    'is_shippable': 0, 'is_taxable': 0, 'auto_create_variants': 0, 'attributes': []}
            pid = self.create(role, '/api/v2/products', body)
            product = self.api.detail('/api/v2/products/' + str(pid))
            if (product.get('sku') != sku or Decimal(str(product.get('price'))) != 10
                    or product.get('is_shippable') not in (0, False)
                    or product.get('taxable', product.get('is_taxable')) not in (0, False)):
                raise ValueError('Synthetic product isolation failed')
            ids.append(pid)
        offers = {n: self.create('offer-' + str(n), '/api/v2/offers', offer_body(*ids, n)) for n in (2, 4)}
        for count, oid in offers.items():
            offer = self.api.detail('/api/v2/offers/' + str(oid))
            profile = offer.get('prepaid_profile') or offer.get('prepaid') or {}
            if (offer.get('cycle_type_id') != 2 or profile.get('is_subscription') not in (1, True)
                    or profile.get('terms', [{}])[0].get('cycles') != count):
                raise ValueError('Custom prepaid offer read-back failed')
        cid = self.create('campaign', '/api/v2/campaigns', {
            'name': RUN + ' Dry Run ONLY', 'description': 'Synthetic refill SKU verification; no fulfillment or notifications.',
            'channel_id': 1, 'gateway_id': 1, 'payment_methods': ['visa'], 'offers': list(offers.values()),
            'countries': [223], 'shipping_profiles': [2], 'return_profiles': [], 'coupon_profiles': [],
            'postback_profiles': [], 'is_prepaid_blocked': 0})
        campaign = self.api.detail('/api/v2/campaigns/' + str(cid))
        if campaign.get('gateway_id') != 1 or any(campaign.get(k) not in (0, '0', None, []) for k in INTEGRATIONS):
            raise ValueError('Dry Run campaign access/isolation needs verification')
        self.state['fixture'] = {'campaign_id': cid, 'initial_product_id': ids[0], 'refill_product_id': ids[1], 'offers': offers}
        self.save()
        return self.state['fixture']

    def view(self, order_id, fixture, count, position):
        result = self.api.call('POST', '/api/v1/order_view', {'order_id': [str(order_id)]})
        if (str(result.get('response_code')) != '100' or str(result.get('is_test_cc')) != '1'
                or int(result.get('gateway_id', 0)) != 1 or int(result.get('campaign_id', 0)) != fixture['campaign_id']):
            raise ValueError('Order did not prove isolated Dry Run routing')
        products = result.get('products', [])
        if len(products) != 1:
            raise ValueError('Unexpected order products')
        product = products[0]
        role = 'INITIAL' if position == 0 else 'REFILL'
        expected_id = fixture['initial_product_id'] if position == 0 else fixture['refill_product_id']
        prepaid = product.get('prepaid') or []
        expected_total = Decimal(10 * count) if position in (0, count) else Decimal(0)
        if (int(product.get('product_id', 0)) != expected_id or product.get('sku') != RUN + '-' + role
                or str(product.get('is_shippable')) != '0' or Decimal(str(result.get('order_total'))) != expected_total
                or len(prepaid) != 1 or int(prepaid[0].get('current_cycle', 0)) != position % count + 1
                or int(prepaid[0].get('total_cycles', 0)) != count or str(prepaid[0].get('is_renew')) != '1'):
            raise ValueError('Refill SKU, full-term amount or prepaid cycle did not match')
        return {'id': str(order_id), 'product_id': expected_id, 'sku_role': role, 'total': str(expected_total),
                'cycle': position % count + 1, 'subscription': product.get('subscription_id'),
                'ancestor': result.get('ancestor_id'), 'next_date': product.get('recurring_date')}

    def orders(self, fixture):
        chains = []
        for count in (2, 4):
            oid = fixture['offers'].get(count) or fixture['offers'].get(str(count))
            body = {'firstName': 'WLMD', 'lastName': 'SyntheticTest', 'shippingAddress1': '1 Synthetic Test Way',
                    'shippingCity': 'San Francisco', 'shippingState': 'CA', 'shippingZip': '94105', 'shippingCountry': 'US',
                    'phone': '2025550100', 'email': f'{RUN}-{count}@example.invalid', 'creditCardType': 'visa',
                    'creditCardNumber': '1444444444444440', 'expirationDate': '1230', 'CVV': '123',
                    'tranType': 'Sale', 'ipAddress': '192.0.2.1', 'campaignId': fixture['campaign_id'],
                    'shippingId': 2, 'billingSameAsShipping': 'YES', 'forceGatewayId': 1, 'preserve_force_gateway': 1,
                    'offers': [{'offer_id': oid, 'product_id': fixture['initial_product_id'], 'billing_model_id': 4,
                                'quantity': 1, 'prepaid_cycles': count}], 'notes': RUN + ' synthetic test only'}
            chain = []
            for position in range(count + 1):
                path = '/api/v1/new_order' if position == 0 else '/api/v1/order_force_bill'
                payload = body if position == 0 else {'order_id': chain[-1]['id'], 'forceGatewayId': 1, 'preserve_force_gateway': 1}
                result = self.write(f'order-{count}-{position}', path, payload)
                if str(result.get('response_code')) != '100' or str(result.get('error_found', '0')) != '0':
                    raise ValueError('Order was not approved; reconcile before proceeding')
                child_id = result.get('new_order_id') or result.get('order_id')
                if not child_id or (chain and str(child_id) == chain[-1]['id']):
                    raise ValueError('Child order ID requires reconciliation')
                chain.append(self.view(child_id, fixture, count, position))
                self.state['verified_orders'] = [*self.state.get('verified_orders', []), chain[-1]]
                self.save()
            if len({r['subscription'] for r in chain}) != 1 or len({r['ancestor'] for r in chain}) != 1:
                raise ValueError('Subscription lineage changed')
            chains.append(chain)
        self.state['result'] = {'status': 'verified', 'synthetic_orders': 8, 'chains': chains}
        self.save()
        return self.state['result']


if __name__ == '__main__':
    import argparse
    import sys
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approved-dry-run', action='store_true', required=True)
    parser.add_argument('--phase', choices=('setup', 'orders'), required=True)
    args = parser.parse_args()
    if os.environ.get('FLY_APP_NAME') != 'wlmd-stripe-test-0f89b1bb':
        parser.error('Run only on the authorized existing Fly host')
    sys.path.insert(0, '/app')
    from app import Sticky
    run = Verification(Sticky(), '/data/' + RUN + '.json')
    fixture = run.setup()
    print(json.dumps(fixture if args.phase == 'setup' else run.orders(fixture)))
