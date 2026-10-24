"""FortifyHP physical prepaid contract; all services below are in-memory fakes."""
import copy
import unittest

from catalog import CatalogError, quote, resolve
from external_fulfillment import fortifyhp_prepaid_supported
from prepaid import configuration
import test_master as master_helpers


class FortifyCatalog:
    def __init__(self, term=12, renewal=True):
        self.calls = []
        self.cycles = term // 3
        self.product = {'id': 99001, 'sku': f'SEMA-{term}M' + ('-SUB' if renewal else ''),
                        'name': 'FortifyHP Semaglutide', 'price': '357.00', 'is_shippable': 1,
                        'taxable': 0, 'archived_flag': 0}
        self.offer = {**configuration(self.cycles, renewal), 'id': 99002,
                      'name': 'FortifyHP full-term plan', 'products': [{'id': 99001}],
                      'billing_models': [{'id': 4, 'days': 90, 'type': {'id': 1}, 'discount': 0}]}
        self.campaign = {'id': 195, 'is_active': 1, 'is_archived': 0, 'gateway_id': 269,
                         'payment_methods': [{'value': 'stripe_link'}],
                         'alternative_payments': [{'payment_method': 'stripe_link',
                                                   'provider': {'id': 269, 'account_id': 250}}],
                         'shipping_profiles': [{'id': 2, 'name': 'Free Shipping'}],
                         'countries': [{'iso_2': 'US', 'name': 'United States'}], 'offers': [self.offer]}
        self.quote_total = str(357 * self.cycles)
        self.quote_cycles = self.cycles

    def detail(self, path):
        if '/campaigns/' in path:
            return copy.deepcopy(self.campaign)
        if '/products/' in path:
            return copy.deepcopy(self.product)
        if '/profiles/' in path:
            return {'account_id': 250, 'currency': {'code': 'USD'},
                    'fields': {'account_fields': {'publishable_key': 'pk_live_placeholder',
                                                 'capture_on_shipment': False, 'enable_delayed_capture': False}}}
        raise AssertionError(path)

    def call(self, method, path, body=None):
        self.calls.append((method, path, copy.deepcopy(body)))
        if path == '/api/v2/order_total/calculate':
            return {'data': {'total': self.quote_total, 'line_items': [{'id': 99001, 'qty': 1,
                      'is_prepaid': True, 'prepaid': {'term': self.quote_cycles, 'total': self.quote_total}}]}}
        raise AssertionError('Unexpected write or payment call: ' + path)


class ExternalFulfillmentTests(unittest.TestCase):
    def test_six_and_twelve_month_contracts_allow_only_agreed_renewal(self):
        for term in (6, 12):
            for renewal in (False, True):
                with self.subTest(term=term, renewal=renewal):
                    fake = FortifyCatalog(term, renewal)
                    self.assertTrue(fortifyhp_prepaid_supported(fake.campaign, fake.product, fake.offer))
                    catalog = resolve(fake, 195, fake.product['sku'])
                    option = catalog['options'][0]
                    self.assertEqual(option['blockedReason'], '')
                    self.assertTrue(option['shippable'])
                    self.assertEqual(option['renewal'], renewal)
                    self.assertEqual(option['renewalDays'], term * 30 if renewal else None)
                    result = quote(fake, catalog, option['key'], 2, {'country': 'US', 'region': 'CA', 'postal_code': '94105'})
                    self.assertEqual(result['amount'], 35700 * (term // 3))
                    self.assertEqual([p for _, p, _ in fake.calls], ['/api/v2/order_total/calculate'])
                    self.assertNotIn('price', fake.calls[0][2]['offers'][0])

    def test_unacknowledged_campaign_gateway_tax_and_wrong_cycle_remain_blocked(self):
        cases = ('campaign', 'gateway', 'route', 'tax', 'sku', 'term', 'renewal', 'days', 'model', 'shipping')
        for case in cases:
            with self.subTest(case=case):
                fake = FortifyCatalog()
                if case == 'campaign': fake.campaign['id'] = 422
                if case == 'gateway': fake.campaign['gateway_id'] = 254
                if case == 'route': fake.campaign['alternative_payments'][0]['provider']['id'] = 254
                if case == 'tax': fake.product['taxable'] = 1
                if case == 'sku': fake.product['sku'] = 'OTHER-12M-SUB'
                if case == 'term': fake.offer['prepaid']['terms'][0]['cycles'] = 2
                if case == 'renewal': fake.offer['prepaid']['is_subscription'] = 0
                if case == 'days': fake.offer['billing_models'][0]['days'] = 30
                if case == 'model': fake.offer['billing_models'][0]['id'] = 3
                if case == 'shipping': fake.campaign['shipping_profiles'] = []
                self.assertFalse(fortifyhp_prepaid_supported(fake.campaign, fake.product, fake.offer))
                catalog = resolve(fake, fake.campaign['id'], fake.product['sku'])
                self.assertTrue(catalog['options'][0]['blockedReason'])

    def test_quote_rejects_shipping_charge_or_wrong_prepaid_count(self):
        for change in ('amount', 'cycles'):
            fake = FortifyCatalog()
            catalog = resolve(fake, 195, fake.product['sku'])
            if change == 'amount': fake.quote_total = '1433.00'
            else: fake.quote_cycles = 3
            with self.assertRaises(CatalogError):
                quote(fake, catalog, catalog['options'][0]['key'], 2,
                      {'country': 'US', 'region': 'CA', 'postal_code': '94105'})
            self.assertTrue(all(path == '/api/v2/order_total/calculate' for _, path, _ in fake.calls))


class ExternalFulfillmentProvisionTests(unittest.TestCase):
    setUp = master_helpers.MasterTests.setUp
    tearDown = master_helpers.MasterTests.tearDown
    post = master_helpers.MasterTests.post
    review = master_helpers.MasterTests.review
    apply = master_helpers.MasterTests.apply
    state = master_helpers.MasterTests.state

    def test_review_and_apply_preserve_physical_product_and_existing_offers(self):
        self.fake.link_gateway = 269
        original = self.fake.detail

        def fortify_detail(path):
            result = original(path)
            if path == '/api/v2/campaigns/195':
                result['gateway_id'] = 269
            return result

        self.fake.detail = fortify_detail
        self.fake.products[99001] = {'id': 99001, 'sku': 'SEMA-12M-SUB', 'name': 'Semaglutide 12 months',
                                    'price': '1428.00', 'category_id': 113, 'cost_of_goods': '0',
                                    'restocking_fee': '0', 'max_quantity': 1,
                                    'is_shippable': 1, 'taxable': 0, 'archived_flag': 0}
        master = {'sku': 'SEMA-12M-SUB', 'name': 'Semaglutide 12 months', 'product_id': 99001,
                  'currency': 'USD', 'offers': [{'id': 'upfront', 'name': '12 months upfront',
                      'price': '1428.00', 'billing_models': [4], 'prepaid_cycles': 4, 'prepaid_renewal': True}]}
        self.assertEqual(self.apply(self.review('master', master)).status_code, 200)
        self.assertEqual(self.apply(self.review('brand', {'id': 'fortifyhp', 'name': 'FortifyHP', 'campaign_id': 195})).status_code, 200)
        review = self.review('provision', {'brand_id': 'fortifyhp', 'campaign_id': 195})
        writes = review['preview']['stickyWrites']
        self.assertEqual(writes[0]['body']['is_shippable'], 1)
        self.assertEqual(writes[0]['body']['price'], 357.0)
        self.assertEqual(writes[-1]['body']['offers'][0], 706)
        applied = self.apply(review)
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertTrue(applied.json()['validation']['ready'])
        slot = self.state()['offers'][0]
        self.assertEqual(self.fake.products[slot['product_id']]['is_shippable'], 1)
        self.assertEqual(self.fake.products[99001]['price'], '1428.00')
        again = self.review('provision', {'brand_id': 'fortifyhp', 'campaign_id': 195})
        self.assertEqual(again['preview']['stickyWrites'], [])
        self.assertEqual(self.fake.count('/new_order'), 0)
        self.assertEqual(self.fake.count('/authorize_payment'), 0)


if __name__ == '__main__':
    unittest.main()
