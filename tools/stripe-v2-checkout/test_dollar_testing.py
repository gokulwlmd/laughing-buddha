"""Offline $1 mode financial boundaries; never calls Sticky or Stripe networks."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from app import Settings, create_app
from prepaid import configuration
from test_checkout import FakeSticky, CONTACT, ORIGIN, SKU


class DollarSticky(FakeSticky):
    def __init__(self, cycles=1, renewal=True):
        super().__init__()
        self.cycles, self.renewal = cycles, renewal
        self.model = 4 if cycles > 1 else 3 if renewal else 2
        self.price = '100.00'
        self.shippable, self.taxable = 0, 0
        self.integration = {}
        self.forced_total = None
        self.renewal_price = None
        self.omit_renewal_price = False
        self.currency = 'USD'

    def offer(self):
        offer = super().offer()
        offer['billing_models'] = [{'id': self.model, 'name': 'Fixed schedule',
                'days': 90 if self.cycles > 1 else 30 if self.renewal else 0, 'type': {'id': 1}}]
        if self.cycles > 1:
            offer.update(configuration(self.cycles, self.renewal))
            offer['is_prepaid'] = 1
        return offer

    def detail(self, path):
        result = super().detail(path)
        if '/campaigns/' in path:
            result.update(self.integration)
        elif '/products/' in path:
            result.update(price=self.price, is_shippable=self.shippable, taxable=self.taxable)
        elif '/profiles/' in path:
            result['currency'] = {'code': self.currency}
        return result

    def call(self, method, path, body=None):
        if path.endswith('/calculate'):
            self.calls.append((method, path, deepcopy(body)))
            line = body['offers'][0]
            total = self.forced_total or format(Decimal(line.get('price', self.price)) * self.cycles, '.2f')
            item = {'id': line['product_id'], 'qty': 1}
            if self.cycles > 1:
                item.update(is_prepaid=1, prepaid={'term': self.cycles, 'total': total})
            return {'status': 'SUCCESS', 'data': {'total': total, 'line_items': [item]}}
        if path.endswith('/order_view'):
            result = super().call(method, path, body)
            offer = next(b['offers'][0] for _, p, b in reversed(self.calls) if p.endswith('/new_order'))
            unit = offer.get('price', self.price)
            result['order_total'] = format(Decimal(unit) * self.cycles, '.2f')
            product = result['products'][0]
            # Real order_view reports the full term renewal amount for prepaid,
            # while new_order takes its per-cycle unit override.
            product['next_subscription_product_price'] = self.renewal_price or format(Decimal(unit) * self.cycles, '.2f')
            if self.omit_renewal_price:
                product.pop('next_subscription_product_price')
            product['price'] = unit
            if self.cycles > 1:
                product['prepaid'] = [{'total_cycles': str(self.cycles), 'current_cycle': '1',
                    'is_renew': str(int(self.renewal))}]
            return result
        return super().call(method, path, body)


class DollarTestingTests(unittest.TestCase):
    def fixture(self, cycles=1, renewal=True, marked=True, campaign=422, enabled=True):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        fake = DollarSticky(cycles, renewal)
        app = create_app(Settings(public_url=ORIGIN, state_dir=Path(directory.name), authorization_verified=True), fake)
        owner = TestClient(app, base_url=ORIGIN)
        self.addCleanup(owner.close)
        owner.get('/admin?setup=' + app.state.admin.setup_token)
        csrf = owner.get('/api/admin/auth').json()['csrfToken']
        response = owner.post('/api/admin/setup', headers={'Origin': ORIGIN, 'X-CSRF-Token': csrf},
            json={'email': 'owner@example.invalid', 'password': 'offline-owner-password-123'})
        self.assertEqual(response.status_code, 200, response.text)
        owner_headers = {'Origin': ORIGIN, 'X-CSRF-Token': response.json()['csrfToken']}
        admin = app.state.admin
        admin.put('brand', 'test-brand', {'id': 'test-brand', 'name': 'Payment test', 'campaign_id': campaign})
        admin.put('site', 'test-site', {'id': 'test-site', 'name': 'Test Site', 'brand_id': 'test-brand', 'campaign_id': campaign})
        admin.put('therapy', 'weight-loss', {'id': 'weight-loss', 'name': 'Weight Loss', 'enabled': True,
            'treatments': [{'id': 'semaglutide', 'name': 'Semaglutide'}]})
        admin.put('master', SKU, {'sku': SKU, 'therapy_id': 'weight-loss', 'treatment_id': 'semaglutide', 'product_duration_months': 12 if cycles == 4 else 6 if cycles == 2 else 1})
        selection = '706:54537:' + str(fake.model)
        admin.put('plan_checkout', 'test-plan', {'id': 'test-plan', 'site_id': 'test-site', 'brand_id': 'test-brand',
            'campaign_id': campaign, 'therapy_id': 'weight-loss', 'enabled': True, 'visibility': 'public',
            'entries': [{'sku': SKU, 'options': [selection]}]})
        admin.put('link', 'test-choice', {'id': 'test-choice', 'brand_id': 'test-brand', 'campaign_id': campaign,
            'sku': SKU, 'title': 'Payment test', 'visibility': 'public', 'enabled': True, 'revision': 1,
            'plan_checkout_id': 'test-plan', 'options': [selection], 'payment_test_only': marked})
        if enabled and campaign == 422:
            saved = owner.put('/api/admin/sites/test-site/checkout-testing', json={'enabled': True}, headers=owner_headers)
            self.assertEqual(saved.status_code, 200, saved.text)
        customer = TestClient(app, base_url=ORIGIN)
        self.addCleanup(customer.close)
        self.assertEqual(customer.get('/c/test-choice').status_code, 200)
        params = {'link_id': 'test-choice'}
        config = customer.get('/api/config', params=params)
        self.assertEqual(config.status_code, 200, config.text)
        headers = {'Origin': ORIGIN, 'X-CSRF-Token': config.json()['csrfToken'], 'X-Checkout-Attempt': config.json()['attemptId']}
        def post(path, body):
            return customer.post('/api/' + path, params=params, headers=headers, json=body)
        def quote(test=True, **extra):
            return post('quote', {'contact': CONTACT, 'selection': selection, 'shipping_id': 2, 'dollar_test': test, **extra})
        return {'app': app, 'fake': fake, 'owner': owner, 'owner_headers': owner_headers, 'customer': customer,
            'post': post, 'quote': quote, 'config': config.json(), 'params': params}

    def authorize(self, f):
        quote = f['quote']()
        self.assertEqual(quote.status_code, 200, quote.text)
        auth = f['post']('authorize', {'quote_id': quote.json()['id'], 'recurring_consent': True})
        self.assertEqual(auth.status_code, 200, auth.text)
        self.assertEqual((quote.json()['amount'], auth.json()['amount']), (100, 100))
        return quote

    def test_one_time_standard_and_prepaid_exact_unit_price_is_preserved(self):
        for cycles, renewal in [(1, False), (1, True), (2, False), (2, True), (4, False), (4, True)]:
            with self.subTest(cycles=cycles, renewal=renewal):
                f = self.fixture(cycles, renewal)
                self.assertTrue(f['config']['dollarTestAvailable'])
                self.authorize(f)
                captured = f['post']('capture', {})
                self.assertEqual(captured.status_code, 200, captured.text)
                self.assertEqual(captured.json()['amount'], 100)
                self.assertEqual(f['post']('capture', {}).status_code, 200)
                self.assertEqual(f['fake'].count('/new_order'), 1)
                unit = {1: '1.00', 2: '0.50', 4: '0.25'}[cycles]
                for _, path, body in f['fake'].calls:
                    if path.endswith('/calculate'):
                        self.assertEqual(body['offers'][0]['price'], unit)
                    elif path.endswith('/authorize_payment'):
                        self.assertEqual(Decimal(body['auth_amount']), Decimal('1.00'))
                    elif path.endswith('/new_order'):
                        self.assertEqual(body['offers'][0]['price'], unit)
                        self.assertEqual(body['offers'][0]['preserve_price'], 1)
                        self.assertEqual(body['offers'][0].get('prepaid_cycles'), cycles if cycles > 1 else None)
                self.assertEqual(f['fake'].price, '100.00')

    def test_mode_requires_owner_setting_and_explicit_test_link_and_campaign(self):
        for marked, campaign, enabled in [(True, 422, False), (False, 422, True), (True, 423, True)]:
            with self.subTest(marked=marked, campaign=campaign, enabled=enabled):
                f = self.fixture(marked=marked, campaign=campaign, enabled=enabled)
                self.assertFalse(f['config']['dollarTestAvailable'])
                self.assertEqual(f['quote']().status_code, 403)
                self.assertEqual(f['fake'].count('/authorize_payment'), 0)
                self.assertEqual(f['fake'].count('/new_order'), 0)

    def test_owner_toggle_cannot_be_changed_by_customer_or_cross_origin(self):
        f = self.fixture(enabled=False)
        path = '/api/admin/sites/test-site/checkout-testing'
        self.assertEqual(f['customer'].get(path).status_code, 401)
        self.assertEqual(f['customer'].put(path, json={'enabled': True}).status_code, 401)
        self.assertEqual(f['owner'].put(path, json={'enabled': True}).status_code, 403)
        self.assertEqual(f['owner'].put(path, json={'enabled': True}, headers=f['owner_headers'] | {'Origin': 'https://other.invalid'}).status_code, 403)
        self.assertEqual(f['owner'].put(path, json={'enabled': True, 'amount': '0.01'}, headers=f['owner_headers']).status_code, 422)
        self.assertEqual(f['quote']().status_code, 403)

    def test_other_site_setting_and_unscoped_checkout_do_not_enable_testing(self):
        f = self.fixture(enabled=False)
        admin = f['app'].state.admin
        admin.put('site', 'other-site', {'id': 'other-site', 'name': 'Other Site', 'brand_id': 'test-brand', 'campaign_id': 422})
        response = f['owner'].put('/api/admin/sites/other-site/checkout-testing',
            json={'enabled': True}, headers=f['owner_headers'])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(f['quote']().status_code, 403)
        admin.put('checkout_testing', 'test-site', {'enabled': True})
        f['owner'].get('/checkout/422/' + SKU)
        params = {'campaign_id': 422, 'sku': SKU}
        config = f['owner'].get('/api/config', params=params).json()
        self.assertFalse(config['dollarTestAvailable'])
        response = f['owner'].post('/api/quote', params=params,
            headers={'Origin': ORIGIN, 'X-CSRF-Token': config['csrfToken'], 'X-Checkout-Attempt': config['attemptId']},
            json={'contact': CONTACT, 'selection': '706:54537:3', 'shipping_id': 2, 'dollar_test': True})
        self.assertEqual(response.status_code, 403)

    def test_normal_price_is_unchanged_even_when_dollar_testing_enabled(self):
        f = self.fixture(cycles=4)
        quoted = f['quote'](False)
        self.assertEqual(quoted.status_code, 200, quoted.text)
        self.assertEqual(quoted.json()['amount'], 40000)
        self.assertNotIn('dollarTest', quoted.json()['option'])
        auth = f['post']('authorize', {'quote_id': quoted.json()['id'], 'recurring_consent': True})
        self.assertEqual(auth.status_code, 200, auth.text)
        self.assertEqual(f['post']('capture', {}).status_code, 200)
        for _, path, body in f['fake'].calls:
            if path.endswith(('/calculate', '/new_order')):
                self.assertNotIn('price', body['offers'][0])
                self.assertNotIn('preserve_price', body['offers'][0])
        self.assertNotIn('NEVER_EXPOSE_THIS', str(f['config']))

    def test_client_cannot_choose_arbitrary_price_or_preserve_flag(self):
        f = self.fixture()
        for injected in [{'amount': 1}, {'price': '0.01'}, {'testUnitPrice': '0.01'}, {'preserve_price': 1}, {'offers': [{'price': '0.01'}]}]:
            with self.subTest(injected=injected):
                self.assertEqual(f['quote'](**injected).status_code, 422)
        self.assertEqual(f['fake'].count('/calculate'), 0)
        self.assertEqual(f['post']('authorize', {'quote_id': 'unused', 'amount': 1}).status_code, 422)
        self.assertEqual(f['post']('capture', {'price': '0.01'}).status_code, 422)

    def test_disabling_before_authorization_blocks_but_after_authorization_keeps_agreed_amount(self):
        f = self.fixture(cycles=2)
        q = f['quote']()
        self.assertEqual(q.status_code, 200, q.text)
        path = '/api/admin/sites/test-site/checkout-testing'
        self.assertEqual(f['owner'].put(path, json={'enabled': False}, headers=f['owner_headers']).status_code, 200)
        blocked = f['post']('authorize', {'quote_id': q.json()['id'], 'recurring_consent': True})
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(f['fake'].count('/authorize_payment'), 0)
        self.assertEqual(f['owner'].put(path, json={'enabled': True}, headers=f['owner_headers']).status_code, 200)
        self.authorize(f)
        self.assertEqual(f['owner'].put(path, json={'enabled': False}, headers=f['owner_headers']).status_code, 200)
        captured = f['post']('capture', {})
        self.assertEqual(captured.status_code, 200, captured.text)
        self.assertEqual(captured.json()['amount'], 100)
        self.assertEqual(f['fake'].count('/new_order'), 1)

    def test_unsafe_product_integrations_or_currency_cannot_use_override(self):
        for field, value in [('shippable', 1), ('taxable', 1), ('tax_provider', 99), ('currency', 'EUR'),
                ('integration', {'fulfillment_id': 99}), ('integration', {'email_provider_id': 99}),
                ('integration', {'postback_profiles': [{'id': 99}]})]:
            with self.subTest(field=field, value=value):
                f = self.fixture()
                setattr(f['fake'], field, value)
                self.assertEqual(f['quote']().status_code, 403)
                self.assertEqual(f['fake'].count('/authorize_payment'), 0)

    def test_non_dollar_calculated_total_is_rejected_before_authorization(self):
        f = self.fixture(cycles=2)
        f['fake'].forced_total = '2.00'
        self.assertEqual(f['quote']().status_code, 502)
        self.assertEqual(f['fake'].count('/authorize_payment'), 0)
        self.assertEqual(f['fake'].count('/new_order'), 0)

    def test_unverified_prepaid_cycle_count_cannot_round_into_an_undercharge(self):
        f = self.fixture(cycles=3)
        self.assertEqual(f['quote']().status_code, 502)
        self.assertEqual(f['fake'].count('/calculate'), 0)
        self.assertEqual(f['fake'].count('/authorize_payment'), 0)

    def test_recurring_capture_with_unpreserved_price_is_held_and_never_retried(self):
        f = self.fixture(cycles=4)
        self.authorize(f)
        f['fake'].renewal_price = '100.00'
        result = f['post']('capture', {})
        self.assertEqual(result.status_code, 502, result.text)
        self.assertEqual(f['post']('capture', {}).status_code, 409)
        self.assertEqual(f['fake'].count('/new_order'), 1)

    def test_nonrenewing_prepaid_shipments_do_not_require_a_next_payment_price(self):
        for cycles in (2, 4):
            for absent in (False, True):
                with self.subTest(cycles=cycles, absent=absent):
                    f = self.fixture(cycles=cycles, renewal=False)
                    quoted = self.authorize(f).json()
                    self.assertTrue(quoted['option']['recurring'])
                    self.assertFalse(quoted['option']['renewal'])
                    f['fake'].renewal_price = '0.00'
                    f['fake'].omit_renewal_price = absent
                    captured = f['post']('capture', {})
                    self.assertEqual(captured.status_code, 200, captured.text)
                    self.assertEqual(captured.json()['amount'], 100)
                    self.assertEqual(f['post']('capture', {}).status_code, 200)
                    self.assertEqual(f['fake'].count('/new_order'), 1)

    def test_actual_renewing_plans_still_require_verified_full_term_renewal_price(self):
        for cycles in (1, 2, 4):
            with self.subTest(cycles=cycles):
                f = self.fixture(cycles=cycles, renewal=True)
                self.authorize(f)
                f['fake'].omit_renewal_price = True
                result = f['post']('capture', {})
                self.assertEqual(result.status_code, 502, result.text)
                self.assertEqual(f['post']('capture', {}).status_code, 409)
                self.assertEqual(f['fake'].count('/new_order'), 1)


if __name__ == '__main__':
    unittest.main()
