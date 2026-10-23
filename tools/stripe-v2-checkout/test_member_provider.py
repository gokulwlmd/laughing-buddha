"""Offline Sticky member adapter contracts; no real accounts or writes."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import unittest

from member_portal.provider import StickyOrderProvider, ProviderError, ProviderRejected, ProviderUncertain
from prepaid import configuration


def order_fixture():
    return {'response_code': '100', 'order_id': '9001', 'campaign_id': '422', 'customer_id': '8001', 'contact_id': '8101',
        'gateway_id': '254', 'first_name': 'Sample', 'last_name': 'Member', 'email_address': 'sample@example.invalid',
        'order_status': '2', 'order_total': '1.00', 'is_test_cc': '0', 'shippable': '0', 'on_hold': '0',
        'ancestor_id': '9001', 'parent_id': '0', 'child_id': '', 'shipping_date': '0000-00-00',
        'time_stamp': '2026-10-23 10:00:00', 'tracking_number': '', 'cc_number': 'DO-NOT-RETURN', 'has_been_posted': '0',
        'shipping_first_name': 'Sample', 'shipping_last_name': 'Member', 'shipping_street_address': '1 Sample St',
        'shipping_street_address2': '', 'shipping_city': 'Tampa', 'shipping_state': 'FL',
        'shipping_postcode': '33601', 'shipping_country': 'US',
        'billing_street_address': 'DO-NOT-RETURN', 'systemNotes': ['DO-NOT-RETURN'],
        'products': [{'product_id': '7001', 'sku': 'SEMA-1M-SUB', 'name': 'Sample Semaglutide',
            'product_qty': '1', 'subscription_id': 'synthetic-subscription-1', 'is_recurring': '1',
            'on_hold': '0', 'recurring_date': '2026-11-22', 'is_shippable': '0', 'is_terminal': '0'}]}


class FakeSticky:
    def __init__(self):
        self.order = order_fixture()
        self.calls = []
        self.wrapper = False
        self.write_error = False
        self.readback_error = False
        self.apply_write = True
        self.write_response = {'response_code': '100'}
        self.subscription = {'id': 'synthetic-subscription-1', 'contact_id': '8101', 'product': {'id': '7001'},
            'status': 'active', 'shipping': {'first_name': 'Sample', 'last_name': 'Member', 'address': '1 Sample St',
                'address2': '', 'city': 'Tampa', 'state': 'FL', 'zip': '33601', 'country_iso2': 'US'}}
        self.billing_model = {'id': 4, 'type': {'id': 1}, 'days': 90, 'is_archived': 0, 'expire_cycles': 0, 'buffer_days': 0}
        self.offer = {'id': 7002, 'products': [{'id': 7001}], 'billing_models': [{'id': 4}],
            'is_archived': 0, **configuration(4, True)}

    def call(self, method, path, body=None):
        self.calls.append((method, path, deepcopy(body)))
        if path == '/api/v1/order_view':
            if self.readback_error and any(p == '/api/v1/subscription_order_update' for _, p, _ in self.calls):
                raise TimeoutError('secret upstream detail')
            value = deepcopy(self.order)
            return {'response_code': '100', 'data': {'9001': value}} if self.wrapper else value
        if path == '/api/v2/providers/payment/profiles/254':
            return {'status': 'SUCCESS', 'data': {'currency': {'code': 'USD'}, 'fields': {'secret': 'DO-NOT-RETURN'}}}
        if path == '/api/v2/billing_models/4':
            return {'status': 'SUCCESS', 'data': deepcopy(self.billing_model)}
        if path == '/api/v2/offers/7002':
            return {'status': 'SUCCESS', 'data': deepcopy(self.offer)}
        if path == '/api/v1/subscription_order_update':
            if self.write_error:
                raise TimeoutError('secret upstream detail')
            if self.apply_write:
                p = self.order['products'][0]
                p['on_hold'] = '1' if body['status'] == 'stop' else '0'
                p['is_recurring'] = '0' if body['status'] == 'stop' else '1'
            return self.write_response
        if path == '/api/v1/order_update':
            if self.write_error: raise TimeoutError('secret upstream detail')
            if self.apply_write:
                keys = {'shipping_address1': 'shipping_street_address', 'shipping_address2': 'shipping_street_address2',
                        'shipping_zip': 'shipping_postcode'}
                for key, value in body['order_id']['9001'].items():
                    self.order[keys.get(key, key)] = value
            return self.write_response
        if path == '/api/v2/subscriptions/synthetic-subscription-1':
            return {'status': 'SUCCESS', 'data': deepcopy(self.subscription)}
        if path == '/api/v2/subscriptions/synthetic-subscription-1/override/address':
            if self.write_error: raise TimeoutError('secret upstream detail')
            if self.apply_write:
                self.subscription['shipping'].update({'address': body['street'], 'city': body['city'],
                    'state': body['state'], 'zip': body['zip'], 'country_iso2': body['country']})
            return {'status': 'SUCCESS'}
        raise AssertionError('Unexpected API call')


class MemberProviderTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeSticky()
        self.provider = StickyOrderProvider(self.api)

    def action(self, action):
        return self.provider.subscription_action('9001', 'synthetic-subscription-1', action,
                                                 expected_campaign='422', expected_customer_id='8001')

    def test_purchased_billing_interval_requires_explicit_fixed_day_model(self):
        product = self.api.order['products'][0]
        for model, expected in [(None, (None, None)), ({'id': '4'}, ('4', None)),
                ({'id': '4', 'days': 90, 'type': {'id': 1}}, ('4', 90)),
                ({'id': '4', 'days': 90, 'type': {'id': 2}}, ('4', None)),
                ({'id': '4', 'days': True, 'type': {'id': 1}}, ('4', None))]:
            with self.subTest(model=model):
                product['billing_model'] = model
                value = self.provider.read_order('9001')['products'][0]
                self.assertEqual((value['billing_model_id'], value['billing_interval_days']), expected)

    def test_future_address_read_uses_owned_subscription_override_not_prior_order(self):
        self.api.subscription['shipping']['address'] = '2 New Street'
        value = self.provider.read_subscription_address('9001', 'synthetic-subscription-1',
            expected_campaign='422', expected_customer_id='8001')
        self.assertEqual(value['address'], '2 New Street')
        self.assertEqual(self.api.order['shipping_street_address'], '1 Sample St')
        self.assertFalse(any(path.endswith('/override/address') for _, path, _ in self.api.calls))
        self.api.subscription['contact_id'] = '9999'
        with self.assertRaises(ProviderRejected):
            self.provider.read_subscription_address('9001', 'synthetic-subscription-1',
                expected_campaign='422', expected_customer_id='8001')

    def test_documented_not_shipped_sentinel_is_not_a_schedule_date(self):
        self.api.order['shipping_date'] = 'Not Shipped'
        self.assertIsNone(self.provider.read_order('9001')['shipping_date'])
        self.api.order['products'][0]['recurring_date'] = 'Not Shipped'
        with self.assertRaises(ProviderError):
            self.provider.read_order('9001')

    def care_fixture(self):
        self.api.order['time_stamp'] = '2026-10-22 19:04:34'
        self.api.order['products'][0].update(billing_model={'id': '4', 'name': '90 days'},
            offer={'id': '7002'}, recurring_date='2027-01-20',
            prepaid=[{'current_cycle': '1', 'total_cycles': '4', 'is_renew': '1'}])

    def verify_care(self, **changes):
        return self.provider.verify_care_schedule('9001', **({'expected_campaign': '422',
            'expected_customer_id': '8001', 'shipment_interval_days': 90, 'shipment_count': 4, 'term_days': 360} | changes))

    def test_care_schedule_uses_original_paid_first_cycle_and_verified_model_offer(self):
        self.care_fixture()
        value = self.verify_care()
        self.assertEqual((value['product_id'], value['offer_id'], value['billing_model_id']), ('7001', '7002', '4'))
        self.assertEqual((value['shipment_interval_days'], value['shipment_count'], value['term_days']), (90, 4, 360))
        self.assertEqual(value['term_started_at'], '2026-10-22 19:04:34')
        self.assertEqual(value['term_order_id'], '9001')
        self.api.order['parent_id'] = '9001'
        self.assertEqual(self.verify_care(), value)
        self.assertNotIn('customer', value)
        self.assertNotIn('sample@example.invalid', json.dumps(value))
        self.assertTrue(all(method == 'GET' or path == '/api/v1/order_view' for method, path, _ in self.api.calls))

    def test_care_schedule_rejects_wrong_site_customer_and_arbitrary_entitlement(self):
        self.care_fixture()
        for changes in [{'expected_campaign': '423'}, {'expected_customer_id': '9999'},
                {'shipment_count': 2, 'term_days': 180}, {'shipment_interval_days': 30, 'term_days': 120},
                {'term_days': 365}, {'shipment_interval_days': True}, {'shipment_count': 1, 'term_days': 90}]:
            with self.subTest(changes=changes):
                with self.assertRaises(ProviderRejected): self.verify_care(**changes)

    def test_care_schedule_rejects_changed_models_offers_and_non_original_orders(self):
        self.care_fixture()
        original_order, original_model, original_offer = deepcopy(self.api.order), deepcopy(self.api.billing_model), deepcopy(self.api.offer)
        changes = [lambda: self.api.order.update(parent_id='8999'),
            lambda: self.api.order.update(child_id='9002'),
            lambda: self.api.order.update(ancestor_id='8999'), lambda: self.api.order.update(order_total='0.00'),
            lambda: self.api.order.update(order_status='6'),
            lambda: self.api.order['products'][0].update(on_hold='1'),
            lambda: self.api.order['products'][0].update(recurring_date='2027-01-21'),
            lambda: self.api.order['products'][0]['prepaid'][0].update(current_cycle='2'),
            lambda: self.api.order['products'][0].pop('offer'),
            lambda: self.api.billing_model.update(days=30), lambda: self.api.billing_model.update(buffer_days=1),
            lambda: self.api.billing_model.update(type={'id': 2}),
            lambda: self.api.offer.update(products=[{'id': 9999}]),
            lambda: self.api.offer.update(billing_models=[{'id': 3}]),
            lambda: self.api.offer['prepaid'].update(is_subscription=0)]
        for index, change in enumerate(changes):
            with self.subTest(case=index):
                self.api.order, self.api.billing_model, self.api.offer = deepcopy(original_order), deepcopy(original_model), deepcopy(original_offer)
                change()
                with self.assertRaises(ProviderRejected): self.verify_care()
        self.assertTrue(all(method == 'GET' or path == '/api/v1/order_view' for method, path, _ in self.api.calls))

    def test_flat_and_wrapped_order_are_normalized_without_sensitive_fields(self):
        flat = self.provider.read_order('9001', expected_campaign='422', expected_customer_id='8001')
        self.api.wrapper = True
        wrapped = self.provider.read_order('9001')
        self.assertEqual(flat, wrapped)
        self.assertEqual(flat['id'], '9001')
        self.assertEqual(flat['customer'], {'name': 'Sample Member', 'email': 'sample@example.invalid'})
        self.assertEqual(flat['payment_status'], 'paid')
        self.assertEqual(flat['fulfillment_status'], 'not_shippable')
        self.assertEqual(flat['currency'], 'USD')
        self.assertEqual(flat['products'][0]['billing_status'], 'active')
        self.assertEqual(flat['products'][0]['next_billing_date'], '2026-11-22')
        self.assertNotIn('DO-NOT-RETURN', json.dumps(flat))
        self.assertEqual(sum(path.startswith('/api/v2/') for _, path, _ in self.api.calls), 1)

    def test_required_identity_status_and_monetary_fields_are_verified(self):
        bad_values = [('response_code', '350'), ('order_id', '9002'), ('customer_id', None),
            ('campaign_id', True), ('products', []), ('order_total', 'NaN'), ('order_total', '-1'),
            ('order_total', '1.001'), ('child_id', 'invalid')]
        for key, value in bad_values:
            with self.subTest(key=key, value=value):
                self.api.order = order_fixture() | {key: value}
                with self.assertRaises(ProviderError): self.provider.read_order('9001')
        self.api.order = order_fixture()
        for kwargs in ({'expected_campaign': '428'}, {'expected_customer_id': '8002'}):
            with self.assertRaises(ProviderRejected): self.provider.read_order('9001', **kwargs)
        for bad in ('../9001', '0', True):
            with self.assertRaises(ProviderError): self.provider.read_order(bad)

    def test_invalid_or_ambiguous_product_data_is_rejected(self):
        for key, value in [('product_id', 'bad'), ('sku', ''), ('product_qty', '0'),
                           ('subscription_id', '../private'), ('recurring_date', 'tomorrow')]:
            self.api.order = order_fixture()
            self.api.order['products'][0][key] = value
            with self.subTest(key=key):
                with self.assertRaises(ProviderError): self.provider.read_order('9001')

    def test_payment_shipping_and_unknown_statuses_stay_separate(self):
        for status, payment in [('1', 'initiated'), ('2', 'paid'), ('3', 'unknown'), ('6', 'void_or_refunded'),
                                ('7', 'declined'), ('8', 'paid'), ('9', 'unknown'), ('11', 'pending'), ('99', 'unknown')]:
            self.api.order = order_fixture() | {'order_status': status, 'shippable': '1'}
            result = self.provider.read_order('9001')
            self.assertEqual(result['payment_status'], payment)
            self.assertEqual(result['fulfillment_status'], 'shipped' if status == '8' else 'unknown')
        self.api.order = order_fixture() | {'is_refund': 'yes', 'amount_refunded_to_date': '0.50'}
        self.assertEqual(self.provider.read_order('9001')['payment_status'], 'partially_refunded')
        self.api.order['amount_refunded_to_date'] = '1.00'
        self.assertEqual(self.provider.read_order('9001')['payment_status'], 'refunded')
        self.api.order['is_void'] = 'yes'
        self.assertEqual(self.provider.read_order('9001')['payment_status'], 'voided')

    def test_prepaid_cycles_do_not_misrepresent_zero_dollar_shipment_as_next_charge(self):
        p = self.api.order['products'][0]
        p['prepaid'] = [{'total_cycles': '4', 'current_cycle': '1', 'is_renew': '1'}]
        product = self.provider.read_order('9001')['products'][0]
        self.assertEqual(product['next_cycle_date'], '2026-11-22')
        self.assertIsNone(product['next_billing_date'])
        self.assertEqual(product['prepaid'], {'current_cycle': 1, 'total_cycles': 4, 'renews': True})
        p['prepaid'][0]['current_cycle'] = '4'
        self.assertEqual(self.provider.read_order('9001')['products'][0]['next_billing_date'], '2026-11-22')
        p['prepaid'][0]['is_renew'] = '0'
        p['is_recurring'] = '0'
        p['recurring_date'] = '0000-00-00'
        completed = self.provider.read_order('9001')['products'][0]
        self.assertEqual(completed['billing_status'], 'completed')
        self.assertIsNone(completed['next_billing_date'])

    def test_no_currency_or_missing_billing_flags_is_not_invented(self):
        self.api.order['gateway_id'] = '0'
        p = self.api.order['products'][0]
        p.pop('is_recurring')
        p.pop('on_hold')
        result = self.provider.read_order('9001')
        self.assertIsNone(result['currency'])
        self.assertEqual(result['products'][0]['billing_status'], 'unknown')
        self.assertIsNone(result['products'][0]['is_recurring'])

    def test_pause_and_resume_use_only_stop_and_reset_then_verify_readback(self):
        paused = self.action('pause')
        self.assertEqual(paused['products'][0]['billing_status'], 'held')
        resumed = self.action('resume')
        self.assertEqual(resumed['products'][0]['billing_status'], 'active')
        writes = [body for _, path, body in self.api.calls if path == '/api/v1/subscription_order_update']
        self.assertEqual(writes, [{'order_id': '9001', 'product_id': '7001', 'status': 'stop'},
                                 {'order_id': '9001', 'product_id': '7001', 'status': 'reset'}])
        self.assertFalse(any(path in ('/api/v1/new_order', '/api/v1/order_force_bill') for _, path, _ in self.api.calls))

    def test_already_reached_state_is_read_only_and_unsupported_actions_never_write(self):
        self.action('resume')
        for action in ('cancel', 'start', 'refund', 'ship', 'force_bill'):
            with self.assertRaises(ProviderRejected): self.action(action)
        self.assertFalse(any(path == '/api/v1/subscription_order_update' for _, path, _ in self.api.calls))

    def test_actions_require_owned_exact_subscription_and_an_unambiguous_product(self):
        with self.assertRaises(ProviderRejected):
            self.provider.subscription_action('9001', 'other-subscription', 'pause',
                                             expected_campaign='422', expected_customer_id='8001')
        with self.assertRaises(ProviderRejected):
            self.provider.subscription_action('9001', 'synthetic-subscription-1', 'pause',
                                             expected_campaign='428', expected_customer_id='8001')
        duplicate = deepcopy(self.api.order['products'][0])
        duplicate['subscription_id'] = 'different-subscription'
        self.api.order['products'].append(duplicate)
        with self.assertRaises(ProviderRejected): self.action('pause')
        self.assertFalse(any(path == '/api/v1/subscription_order_update' for _, path, _ in self.api.calls))

    def test_unknown_write_outcomes_and_failed_readbacks_are_held_without_retries(self):
        for failure in ('timeout', 'readback', 'unchanged', 'rejected'):
            self.api = FakeSticky()
            self.provider = StickyOrderProvider(self.api)
            self.api.write_error = failure == 'timeout'
            self.api.readback_error = failure == 'readback'
            self.api.apply_write = failure != 'unchanged'
            if failure == 'rejected': self.api.write_response = {'response_code': '911'}
            with self.subTest(failure=failure):
                with self.assertRaises(ProviderUncertain) as caught: self.action('pause')
                self.assertNotIn('secret upstream detail', str(caught.exception))
                self.assertEqual(sum(path == '/api/v1/subscription_order_update' for _, path, _ in self.api.calls), 1)

    def test_archived_orders_and_one_time_orders_cannot_be_restarted(self):
        self.api.order['order_status'] = '3'
        with self.assertRaises(ProviderRejected): self.action('pause')
        self.api.order = order_fixture()
        self.api.order['products'][0]['is_recurring'] = '0'
        with self.assertRaises(ProviderRejected): self.action('resume')
        self.api.order['products'][0]['on_hold'] = '1'
        self.api.order['products'][0]['recurring_date'] = '0000-00-00'
        with self.assertRaises(ProviderRejected): self.action('resume')

    def address(self):
        return {'first_name': 'Sample', 'last_name': 'Member', 'address': '2 Fictional Avenue',
                'address2': '', 'city': 'Seattle', 'region': 'WA', 'postal_code': '98101', 'country': 'US'}

    def test_order_address_update_changes_only_shipping_and_confirms_readback(self):
        result = self.provider.update_address('9001', self.address(), expected_campaign='422', expected_customer_id='8001')
        self.assertEqual(result['shipping_address'], self.address())
        writes = [body for _, route, body in self.api.calls if route == '/api/v1/order_update']
        self.assertEqual(len(writes), 1)
        self.assertTrue(all(key.startswith('shipping_') for key in writes[0]['order_id']['9001']))
        self.assertEqual(self.api.order['billing_street_address'], 'DO-NOT-RETURN')

    def test_shipped_posted_historical_or_unknown_orders_cannot_change_address(self):
        for change in ({'order_status': '8'}, {'has_been_posted': '1'}, {'has_been_posted': None},
                       {'tracking_number': 'SAMPLE-TRACKING'}, {'child_id': '9002'}, {'shipping_date': '10/23/2026'}):
            self.api.order = order_fixture() | change
            with self.subTest(change=change):
                with self.assertRaises(ProviderRejected):
                    self.provider.update_address('9001', self.address(), expected_campaign='422', expected_customer_id='8001')
        self.assertFalse(any(route == '/api/v1/order_update' for _, route, _ in self.api.calls))

    def test_address_fields_are_allowlisted_and_unknown_write_results_are_not_retried(self):
        for change in ({'billing_address': 'tampered'}, {'region': 'Washington'}, {'country': 'CA'},
                       {'postal_code': 'bad'}, {'first_name': ''}):
            with self.assertRaises(ProviderRejected):
                self.provider.update_address('9001', self.address() | change, expected_campaign='422', expected_customer_id='8001')
        self.api.write_error = True
        with self.assertRaises(ProviderUncertain):
            self.provider.update_address('9001', self.address(), expected_campaign='422', expected_customer_id='8001')
        self.assertEqual(sum(route == '/api/v1/order_update' for _, route, _ in self.api.calls), 1)

    def test_future_subscription_address_is_scoped_and_separate_from_existing_order(self):
        before = self.provider.read_order('9001')['shipping_address']
        result = self.provider.update_subscription_address('9001', 'synthetic-subscription-1', self.address(),
                                                           expected_campaign='422', expected_customer_id='8001')
        self.assertEqual(result['shipping_address'], before)
        self.assertEqual(result['products'][0]['subscription_shipping_address'], self.address())
        writes = [(route, body) for method, route, body in self.api.calls if method == 'POST' and 'override/address' in route]
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][1], {'street': '2 Fictional Avenue', 'city': 'Seattle', 'state': 'WA', 'zip': '98101', 'country': 'US'})

    def test_subscription_address_rejects_foreign_contact_and_undocumented_field_changes(self):
        self.api.subscription['contact_id'] = '8102'
        with self.assertRaises(ProviderRejected):
            self.provider.update_subscription_address('9001', 'synthetic-subscription-1', self.address(),
                                                       expected_campaign='422', expected_customer_id='8001')
        self.api.subscription['contact_id'] = '8101'
        for change in ({'address2': 'Unit 5'}, {'first_name': 'Changed'}):
            with self.assertRaises(ProviderRejected):
                self.provider.update_subscription_address('9001', 'synthetic-subscription-1', self.address() | change,
                                                           expected_campaign='422', expected_customer_id='8001')
        self.assertFalse(any('override/address' in route for _, route, _ in self.api.calls))

    def test_unconfirmed_subscription_address_readback_is_held(self):
        self.api.apply_write = False
        with self.assertRaises(ProviderUncertain):
            self.provider.update_subscription_address('9001', 'synthetic-subscription-1', self.address(),
                                                       expected_campaign='422', expected_customer_id='8001')
        self.assertEqual(sum('override/address' in route for _, route, _ in self.api.calls), 1)


class IncludedCycleSticky(FakeSticky):
    """Offline native-cycle contract. Every write is recorded, never networked."""
    def __init__(self, *, renews=True, cycles=4, live=False):
        super().__init__()
        self.order.update(order_total='100.00', gateway_id='254' if live else '1', is_test_cc='0' if live else '1',
            time_stamp='2026-10-22 19:04:34', ancestor_id='9001', parent_id='9001', child_id='',
            shipping_id='2', shipping_amount='0.00', order_sales_tax_amount='0.00')
        self.order['products'][0].update(sku='SEMA-12M-SUB', offer={'id': '7002'}, billing_model={'id': '4'},
            recurring_date='2027-01-20', prepaid=[{'current_cycle': '1', 'total_cycles': str(cycles), 'is_renew': str(int(renews))}])
        self.orders = {'9001': self.order}
        self.offer.update(configuration(cycles, renews))
        self.campaign = {'id': 422, 'is_active': 1, 'is_archived': 0, 'gateway_id': 254,
            'offers': [{'id': 7002}], 'fulfillment_id': 0, 'tax_provider_id': 0,
            'email_provider_id': 0, 'membership_provider_id': 0, 'postback_profiles': []}
        self.product = {'id': 7001, 'sku': 'SEMA-12M-SUB', 'is_shippable': 0, 'taxable': 0}
        self.gateway = {'id': 254 if live else 1, 'account_id': 250 if live else 10,
            'account_name': 'Stripe Connect v2' if live else 'Dry Run Testing', 'currency': {'code': 'USD'}}
        self.shipping = {'id': 2, 'amount_recurring': '0.00'}
        self.failure = None
        self.child_change = None

    def call(self, method, path, body=None):
        self.calls.append((method, path, deepcopy(body)))
        wrote = any(p == '/api/v1/order_force_bill' for _, p, _ in self.calls)
        if path == '/api/v1/order_view':
            if wrote and self.failure == 'readback': raise TimeoutError('secret readback detail')
            return deepcopy(self.orders[body['order_id'][0]])
        details = {'/api/v2/campaigns/422': self.campaign, '/api/v2/products/7001': self.product,
            '/api/v2/offers/7002': self.offer, '/api/v2/billing_models/4': self.billing_model,
            '/api/v2/providers/payment/profiles/' + str(self.gateway['id']): self.gateway,
            '/api/v2/shipping/2': self.shipping}
        if path in details: return {'status': 'SUCCESS', 'data': deepcopy(details[path])}
        if path == '/api/v1/order_force_bill':
            parent = self.orders[body['order_id']]
            child = deepcopy(parent)
            child_id = str(int(parent['order_id']) + 1)
            # Actual Sticky native $0 child readback omits the shipping ID even
            # though the original still identifies the free shipping profile.
            child.update(order_id=child_id, parent_id=parent['order_id'], child_id='', order_total='0.00', shipping_id=None)
            line = child['products'][0]
            line['prepaid'][0]['current_cycle'] = str(int(line['prepaid'][0]['current_cycle']) + 1)
            final = line['prepaid'][0]['current_cycle'] == line['prepaid'][0]['total_cycles']
            if final and line['prepaid'][0]['is_renew'] == '0':
                line.update(is_recurring='0', recurring_date='0000-00-00')
            else:
                line.update(is_recurring='1', recurring_date='2027-01-21')
            # Actual Sticky ancestors list all descendants, not just their
            # immediate child. Keep parent_id as the direct native lineage.
            ancestor, visited = parent, set()
            while ancestor['order_id'] not in visited:
                visited.add(ancestor['order_id'])
                descendants = [value for value in ancestor['child_id'].split(',') if value]
                ancestor['child_id'] = ','.join(descendants + [child_id])
                ancestor = self.orders.get(ancestor['parent_id'])
                if ancestor is None:
                    break
            parent['products'][0]['is_recurring'] = '0'
            if self.child_change: self.child_change(child)
            self.orders[child_id] = child
            if self.failure == 'force_timeout': raise TimeoutError('secret timeout detail')
            if self.failure == 'force_decline': return {'response_code': '800', 'error_found': '1', 'order_id': child_id}
            return {'response_code': '100', 'error_found': '0', 'order_id': child_id}
        if path == '/api/v1/subscription_order_update':
            if self.failure == 'date_timeout': raise TimeoutError('secret date detail')
            if self.failure != 'date_unchanged':
                self.orders[body['order_id']]['products'][0]['recurring_date'] = datetime.strptime(body['new_recurring_date'], '%m/%d/%Y').date().isoformat()
            return {'response_code': '100', 'new_recurring_date': {'response_code': '911' if self.failure == 'date_partial' else '100'}}
        raise AssertionError('Unexpected API call ' + path)


class IncludedCycleProviderTests(unittest.TestCase):
    def setUp(self):
        self.api = IncludedCycleSticky()
        self.provider = StickyOrderProvider(self.api, wall_clock=lambda: datetime(2026, 10, 23, tzinfo=timezone.utc).timestamp())
        self.scope = {'expected_campaign': '422', 'expected_customer_id': '8001',
            'expected_subscription_id': 'synthetic-subscription-1', 'expected_product_id': '7001',
            'expected_offer_id': '7002', 'expected_billing_model_id': '4', 'term_order_id': '9001',
            'term_started_at': '2026-10-22 19:04:34', 'shipment_interval_days': 90,
            'shipment_count': 4, 'target_cycle': 2}

    def writes(self):
        return [(p, b) for m, p, b in self.api.calls if m != 'GET' and p != '/api/v1/order_view']

    def test_capability_reads_fresh_configuration_without_writes_or_sensitive_output(self):
        proof = self.provider.included_cycle_capability('9001', **self.scope)
        self.assertEqual((proof['amount'], proof['target_cycle'], proof['following_cycle_date']), ('0.00', 2, '2027-04-20'))
        self.assertEqual(self.writes(), [])
        self.assertNotIn('sample@example.invalid', json.dumps(proof))

    def test_native_claims_create_only_three_zero_children_and_preserve_anchors(self):
        current = '9001'
        for cycle, following in [(2, '2027-04-20'), (3, '2027-07-19'), (4, '2027-10-17')]:
            scope = self.scope | {'target_cycle': cycle}
            child = self.provider.advance_included_cycle(current, **scope)
            self.assertEqual(child['total'], '0.00')
            self.assertEqual(child['products'][0]['prepaid']['current_cycle'], cycle)
            self.assertEqual(child['products'][0]['next_cycle_date'], following)
            count = len(self.writes())
            self.assertEqual(self.provider.reconcile_included_cycle(current, **scope), child)
            self.assertEqual(len(self.writes()), count)
            current = child['id']
        with self.assertRaises(ProviderRejected):
            self.provider.advance_included_cycle(current, **(self.scope | {'target_cycle': 5}))
        force = [body for path, body in self.writes() if path.endswith('order_force_bill')]
        self.assertEqual(len(force), 3)
        self.assertTrue(all(body['product_id'] == '7001' and body['forceGatewayId'] == 1 and body['preserve_force_gateway'] == 1 for body in force))
        self.assertTrue(all(path in ('/api/v1/order_force_bill', '/api/v1/subscription_order_update') for path, _ in self.writes()))

    def test_live_gateway_is_never_overridden(self):
        self.api = IncludedCycleSticky(live=True)
        self.provider.api = self.api
        self.provider.advance_included_cycle('9001', **self.scope)
        force = [body for path, body in self.writes() if path.endswith('order_force_bill')]
        self.assertEqual(force, [{'order_id': '9001', 'product_id': '7001'}])

    def test_descendant_lists_accept_only_the_verified_native_chain(self):
        first = self.provider.advance_included_cycle('9001', **self.scope)
        second = self.provider.advance_included_cycle(first['id'], **(self.scope | {'target_cycle': 3}))
        self.assertEqual(self.api.order['child_id'], '9002,9003')
        scope = self.scope | {'target_cycle': 4}
        self.assertTrue(self.provider.included_cycle_capability(second['id'], **scope)['available'])
        before = len(self.writes())
        saved = deepcopy(self.api.orders)
        for order_id, child_ids in [('9001', '9002,9003,9999'), ('9001', '9002,9003,9003'),
                                   ('9001', '9003'), ('9002', '9003,9999')]:
            self.api.orders = deepcopy(saved); self.api.order = self.api.orders['9001']
            self.api.orders[order_id]['child_id'] = child_ids
            with self.subTest(order_id=order_id, child_ids=child_ids), self.assertRaises(ProviderRejected):
                self.provider.advance_included_cycle(second['id'], **scope)
            self.assertEqual(len(self.writes()), before)
        self.api.orders = deepcopy(saved); self.api.order = self.api.orders['9001']
        # API variants returning only the direct child remain valid.
        self.api.order['child_id'] = '9002'
        self.assertTrue(self.provider.included_cycle_capability(second['id'], **scope)['available'])

    def test_missing_later_native_shipping_id_rechecks_original_free_profile(self):
        child = self.provider.advance_included_cycle('9001', **self.scope)
        self.assertIsNone(child['shipping_id'])
        before = len(self.api.calls)
        proof = self.provider.included_cycle_capability(child['id'], **(self.scope | {'target_cycle': 3}))
        self.assertTrue(proof['available'])
        self.assertIn(('GET', '/api/v2/shipping/2', None), self.api.calls[before:])
        self.assertTrue(all(method == 'GET' or path == '/api/v1/order_view' for method, path, _ in self.api.calls[before:]))

    def test_shipping_fallback_rejects_changed_profile_missing_original_and_charges(self):
        child = self.provider.advance_included_cycle('9001', **self.scope)
        original, later, profile = deepcopy(self.api.order), deepcopy(self.api.orders[child['id']]), deepcopy(self.api.shipping)
        mutations = [lambda: self.api.orders[child['id']].update(shipping_id='3'),
            lambda: self.api.order.update(shipping_id=None),
            lambda: self.api.shipping.update(amount_recurring='1.00'),
            lambda: self.api.shipping.update(threshold_amount='1.00', threshold_charge_amount='1.00'),
            lambda: self.api.orders[child['id']].update(shipping_amount='1.00'),
            lambda: self.api.orders[child['id']].update(order_total='1.00'),
            lambda: self.api.orders[child['id']].update(order_sales_tax_amount='1.00')]
        for mutate in mutations:
            self.api.order = deepcopy(original); self.api.orders['9001'] = self.api.order
            self.api.orders[child['id']] = deepcopy(later); self.api.shipping = deepcopy(profile)
            before = len(self.writes())
            mutate()
            with self.subTest(mutation=mutate), self.assertRaises(ProviderError):
                self.provider.advance_included_cycle(child['id'], **(self.scope | {'target_cycle': 3}))
            self.assertEqual(len(self.writes()), before)

    def test_nonrenewing_final_included_cycle_stays_completed_without_reactivation(self):
        self.api = IncludedCycleSticky(renews=False, cycles=2)
        self.provider.api = self.api
        child = self.provider.advance_included_cycle('9001', **(self.scope | {'shipment_count': 2}))
        self.assertEqual(child['products'][0]['billing_status'], 'completed')
        self.assertIsNone(child['products'][0]['next_cycle_date'])
        self.assertEqual([path for path, _ in self.writes()], ['/api/v1/order_force_bill'])

    def test_changed_scope_schedule_and_renewal_boundary_are_rejected_before_writes(self):
        for change in [{'expected_campaign': '423'}, {'expected_customer_id': '9999'}, {'expected_product_id': '9'},
                {'expected_subscription_id': 'foreign'}, {'expected_offer_id': '9'}, {'expected_billing_model_id': '9'},
                {'term_started_at': '2026-10-21'}, {'target_cycle': 3}, {'target_cycle': 5},
                {'target_cycle': True}, {'shipment_count': 2}, {'shipment_interval_days': 30}]:
            with self.subTest(change=change), self.assertRaises(ProviderError):
                self.provider.advance_included_cycle('9001', **(self.scope | change))
        self.assertEqual(self.writes(), [])

    def test_unsafe_external_capabilities_fail_closed_before_force_bill(self):
        for mutate in [lambda a: a.product.update(is_shippable=1), lambda a: a.product.update(taxable=1),
                lambda a: a.campaign.update(fulfillment_id=5), lambda a: a.campaign.update(tax_provider_id=5),
                lambda a: a.campaign.update(postback_profiles=[{'id': 1}]), lambda a: a.campaign.update(email_provider_id=5),
                lambda a: a.campaign.update(membership_provider_id=5), lambda a: a.shipping.update(amount_recurring='1.00'),
                lambda a: a.gateway.update(account_id=250), lambda a: a.order.update(shipping_id=''),
                lambda a: a.order.update(order_status='6'), lambda a: a.order.update(child_id='9002'),
                lambda a: a.order['products'][0].update(on_hold='1'),
                lambda a: a.order['products'][0].update(is_terminal='1'),
                lambda a: a.billing_model.update(days=30)]:
            self.api = IncludedCycleSticky(); self.provider.api = self.api
            mutate(self.api)
            with self.subTest(mutate=mutate), self.assertRaises(ProviderError):
                self.provider.advance_included_cycle('9001', **self.scope)
            self.assertEqual(self.writes(), [])

    def test_due_or_past_actual_utc_date_cannot_be_bypassed_by_virtual_care_clock(self):
        for day in (20, 21):
            self.provider.wall_clock = lambda day=day: datetime(2027, 1, day, tzinfo=timezone.utc).timestamp()
            with self.assertRaises(ProviderRejected): self.provider.advance_included_cycle('9001', **self.scope)
        self.assertEqual(self.writes(), [])

    def test_uncertain_writes_and_unverified_children_never_retry_or_change_date(self):
        changes = [lambda c: c.update(order_total='100.00'), lambda c: c.update(customer_id='9999'),
            lambda c: c.update(campaign_id='423'), lambda c: c.update(ancestor_id='8999'),
            lambda c: c.update(parent_id='8999'), lambda c: c['products'][0].update(subscription_id='other'),
            lambda c: c['products'][0].update(offer={'id': '7999'}),
            lambda c: c['products'][0]['prepaid'][0].update(current_cycle='1')]
        for mutate in changes:
            self.api = IncludedCycleSticky(); self.provider.api = self.api; self.api.child_change = mutate
            with self.subTest(mutate=mutate), self.assertRaises(ProviderUncertain):
                self.provider.advance_included_cycle('9001', **self.scope)
            self.assertEqual([path for path, _ in self.writes()], ['/api/v1/order_force_bill'])
        for failure in ('force_timeout', 'force_decline', 'readback', 'date_timeout', 'date_partial', 'date_unchanged'):
            self.api = IncludedCycleSticky(); self.provider.api = self.api; self.api.failure = failure
            with self.subTest(failure=failure), self.assertRaises(ProviderUncertain) as caught:
                self.provider.advance_included_cycle('9001', **self.scope)
            self.assertNotIn('secret', str(caught.exception))
            self.assertEqual(sum(path.endswith('order_force_bill') for path, _ in self.writes()), 1)
            self.assertLessEqual(sum(path.endswith('subscription_order_update') for path, _ in self.writes()), 1)

    def test_reconciliation_never_repairs_an_unconfirmed_schedule_or_repeats_force(self):
        self.api.failure = 'date_timeout'
        with self.assertRaises(ProviderUncertain): self.provider.advance_included_cycle('9001', **self.scope)
        before = len(self.writes())
        with self.assertRaises(ProviderRejected): self.provider.reconcile_included_cycle('9001', **self.scope)
        self.assertEqual(len(self.writes()), before)
        self.api.orders['9002']['products'][0]['recurring_date'] = '2027-04-20'
        child = self.provider.reconcile_included_cycle('9001', child_order_id='9002', **self.scope)
        self.assertEqual(child['id'], '9002')
        self.assertEqual(len(self.writes()), before)


if __name__ == '__main__':
    unittest.main()
