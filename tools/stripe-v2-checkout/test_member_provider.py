"""Offline Sticky member adapter contracts; no real accounts or writes."""
from copy import deepcopy
import json
import unittest

from member_portal.provider import StickyOrderProvider, ProviderError, ProviderRejected, ProviderUncertain


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

    def call(self, method, path, body=None):
        self.calls.append((method, path, deepcopy(body)))
        if path == '/api/v1/order_view':
            if self.readback_error and any(p == '/api/v1/subscription_order_update' for _, p, _ in self.calls):
                raise TimeoutError('secret upstream detail')
            value = deepcopy(self.order)
            return {'response_code': '100', 'data': {'9001': value}} if self.wrapper else value
        if path == '/api/v2/providers/payment/profiles/254':
            return {'status': 'SUCCESS', 'data': {'currency': {'code': 'USD'}, 'fields': {'secret': 'DO-NOT-RETURN'}}}
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


if __name__ == '__main__':
    unittest.main()
