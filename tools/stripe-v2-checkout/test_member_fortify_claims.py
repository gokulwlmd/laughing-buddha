"""Acknowledged production-shipping contract, with a fully offline provider."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

from member_portal.provider import ProviderError, ProviderRejected, ProviderUncertain
from test_member_provider import IncludedCycleSticky
import test_member_provider as provider_tests
import test_member_native_claims as native_tests
import test_member_care as care
import test_member_portal as portal


def fortify_fixture(api):
    api.order.update(campaign_id='195', gateway_id='269', is_test_cc='0', shippable='1',
                     order_status='8', shipping_date='2026-10-23', tracking_number='OFFLINE-TRACKING', has_been_posted='1')
    api.order['products'][0]['is_shippable'] = '1'
    api.product['is_shippable'] = 1
    api.campaign.update(id=195, gateway_id=269, shipping_profiles=[{'id': 2}], countries=[{'iso_2': 'US'}],
        alternative_payments=[{'payment_method': 'stripe_link', 'provider': {'id': 269, 'account_id': 250}}])
    api.gateway.update(id=269, account_id=250, account_name='Stripe Connect v2')
    api.offer['billing_models'] = [deepcopy(api.billing_model)]
    api.child_change = lambda child: child.update(order_status='2', shipping_date='Not Shipped', tracking_number='', has_been_posted='0')
    return api


class FortifyIncludedCycleProviderTests(unittest.TestCase):
    def setUp(self):
        provider_tests.IncludedCycleProviderTests.setUp(self)
        self.api = fortify_fixture(IncludedCycleSticky(live=True))
        self.provider.api = self.api
        self.scope['expected_campaign'] = '195'

    writes = provider_tests.IncludedCycleProviderTests.writes

    def test_fulfilled_ancestors_keep_the_paid_term_and_three_zero_children(self):
        current = '9001'
        for cycle, following in [(2, '2027-04-20'), (3, '2027-07-19'), (4, '2027-10-17')]:
            scope = self.scope | {'target_cycle': cycle}
            proof = self.provider.included_cycle_capability(current, **scope)
            self.assertEqual(proof['mode'], 'external_sticky_orders')
            child = self.provider.advance_included_cycle(current, **scope)
            self.assertEqual(child['total'], '0.00')
            self.assertIs(child['products'][0]['is_shippable'], True)
            self.assertEqual(child['products'][0]['next_cycle_date'], following)
            self.assertEqual(self.provider.reconcile_included_cycle(current, **scope), child)
            current = child['id']
            self.api.orders[current].update(order_status='8', has_been_posted='1', shipping_date='2026-10-24', tracking_number='OFFLINE-CHILD')
        force = [body for path, body in self.writes() if path.endswith('/order_force_bill')]
        self.assertEqual(len(force), 3)
        self.assertTrue(all(set(body) == {'order_id', 'product_id'} for body in force))
        with self.assertRaises(ProviderRejected):
            self.provider.advance_included_cycle(current, **(self.scope | {'target_cycle': 5}))

    def test_outside_campaign_gateway_sku_or_fresh_contract_remains_blocked(self):
        changes = [lambda a: a.order.update(campaign_id='422'), lambda a: a.order.update(gateway_id='254'),
            lambda a: a.order.update(is_test_cc='1'), lambda a: a.order.update(has_been_posted=None),
            lambda a: a.order['products'][0].update(sku='OTHER-12M-SUB'),
            lambda a: a.product.update(is_shippable=0), lambda a: a.product.update(taxable=1),
            lambda a: a.campaign.update(gateway_id=254), lambda a: a.campaign.update(alternative_payments=[]),
            lambda a: a.campaign.update(shipping_profiles=[{'id': 3}]), lambda a: a.campaign.update(countries=[]),
            lambda a: a.offer['billing_models'][0].update(days=30), lambda a: a.shipping.update(amount_recurring='1.00'),
            lambda a: a.order.update(shipping_amount='1.00'), lambda a: a.order.update(order_sales_tax_amount='1.00')]
        for change in changes:
            self.api = fortify_fixture(IncludedCycleSticky(live=True)); self.provider.api = self.api
            change(self.api)
            with self.subTest(change=change), self.assertRaises(ProviderError):
                self.provider.advance_included_cycle('9001', **self.scope)
            self.assertEqual(self.writes(), [])

    def test_six_month_term_has_one_included_child_and_correct_stop_or_renewal(self):
        for renews in (False, True):
            self.api = fortify_fixture(IncludedCycleSticky(live=True, cycles=2, renews=renews))
            self.provider.api = self.api
            sku = 'SEMA-6M' + ('-SUB' if renews else '')
            self.api.order['products'][0]['sku'] = self.api.product['sku'] = sku
            scope = self.scope | {'shipment_count': 2}
            child = self.provider.advance_included_cycle('9001', **scope)
            self.assertEqual(child['total'], '0.00')
            self.assertEqual(child['products'][0]['next_cycle_date'], '2027-04-20' if renews else None)
            self.assertEqual(child['products'][0]['billing_status'], 'active' if renews else 'completed')
            with self.assertRaises(ProviderRejected):
                self.provider.advance_included_cycle(child['id'], **(scope | {'target_cycle': 3}))
            self.assertEqual(sum(path.endswith('/order_force_bill') for path, _ in self.writes()), 1)

    def test_nonzero_or_foreign_child_is_held_after_only_one_native_write(self):
        for change in [lambda c: c.update(order_total='100.00'), lambda c: c.update(customer_id='9999'),
                       lambda c: c.update(parent_id='8999'), lambda c: c.update(has_been_posted=None)]:
            self.api = fortify_fixture(IncludedCycleSticky(live=True)); self.provider.api = self.api; self.api.child_change = change
            with self.subTest(change=change), self.assertRaises(ProviderUncertain):
                self.provider.advance_included_cycle('9001', **self.scope)
            self.assertEqual([p for p, _ in self.writes()], ['/api/v1/order_force_bill'])


class FortifyNativeClaimTests(unittest.TestCase):
    tearDown = portal.MemberPortalTests.tearDown
    post_owner = portal.MemberPortalTests.post_owner
    enroll = portal.MemberPortalTests.enroll
    claim = native_tests.NativeClaimTests.claim
    complete = care.MemberCareTests.complete
    forces = native_tests.NativeClaimTests.forces

    def setUp(self):
        portal.MemberPortalTests.setUp(self)
        self.fake = fortify_fixture(care.configure_native_care_fixture(self.app))
        self.sku = 'SEMA-12M-SUB'
        admin = self.app.state.admin
        for kind, key in [('site', 'site-a'), ('brand', 'brand-a'), ('plan_checkout', 'plan-a'), ('link', 'member-link-a')]:
            row = admin.get(kind, key); row['campaign_id'] = 195
            if kind == 'plan_checkout': row['payment_test_only'] = False
            admin.put(kind, key, row)
        with self.app.state.store.db() as db:
            db.execute("UPDATE checkouts SET campaign=195 WHERE order_id='9001'")
        now = datetime(2026, 10, 22, 19, 4, 34, tzinfo=timezone.utc) + timedelta(days=80)
        self.service.clock = self.service.provider.wall_clock = lambda: now.timestamp()
        self.enroll()
        self.care_path = self.base + '/orders/9001/care-plan'

    def test_real_order_shape_keeps_initial_intake_scope_and_duplicate_guards(self):
        first = self.claim()
        self.assertEqual(first.status_code, 409, first.text)
        self.assertEqual(self.forces(), [])
        self.complete('initial')
        result = self.claim()
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['claim']['order_id'], '9002')
        self.assertEqual(self.fake.orders['9002']['order_total'], '0.00')
        self.assertEqual(self.claim(key='different-request').status_code, 200)
        self.assertEqual(len(self.forces()), 1)
        foreign = self.client.post('/api/v1/sites/site-b/portal/orders/9001/care-tasks/checkin-90/claim',
            headers=self.patient_headers, json={'client_request_id': 'cross-site-request'})
        self.assertEqual(foreign.status_code, 401)
        self.assertEqual(len(self.forces()), 1)
        intake = self.client.get(self.base + '/orders/9001/care-tasks/checkin-90/intake', headers=self.patient_headers)
        self.assertEqual(intake.status_code, 200, intake.text)
        self.assertEqual(intake.json()['claim_order_id'], '9002')


if __name__ == '__main__':
    unittest.main()
