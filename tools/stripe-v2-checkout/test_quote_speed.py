"""Public quote setup reuse never weakens fresh financial validation."""
import unittest
import test_site_session_api as session_tests
from test_checkout import CONTACT
from test_coupons import attach_coupon


class QuoteSpeedTests(unittest.TestCase):
    setUp=session_tests.SessionApiTests.setUp
    tearDown=session_tests.SessionApiTests.tearDown
    create=session_tests.SessionApiTests.create
    configured=session_tests.SessionApiTests.configured
    quoted=session_tests.SessionApiTests.quoted

    def test_config_warms_quote_but_prices_gateway_and_calculator_stay_fresh(self):
        path,headers,_=self.configured();self.fake.reads.clear()
        for total in ('2.00','3.00'):
            self.fake.total=total
            result=self.client.post(path+'/quote',headers=headers,json={'contact':CONTACT,'shipping_id':2})
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.json()['amount'],int(float(total)*100))
        self.assertFalse(any('/campaigns/' in p for p in self.fake.reads))
        self.assertEqual(self.fake.reads.count('/api/v2/products/54537'),2)
        self.assertEqual(self.fake.reads.count('/api/v2/providers/payment/profiles/254'),2)
        self.assertEqual(self.fake.count('/calculate'),2)
        self.assertEqual(self.fake.count('/authorize_payment'),0)

    def test_campaign_drift_blocks_payment_and_refreshes_next_quote(self):
        path,headers,_,q=self.quoted();self.fake.tax_provider=88
        r=self.client.post(path+'/payment',headers=headers,json={'quote_id':q['quote_id']})
        self.assertEqual(r.status_code,409,r.text)
        self.assertEqual(self.fake.count('/authorize_payment'),0)
        q2=self.client.post(path+'/quote',headers=headers,json={'contact':CONTACT,'shipping_id':2}).json()
        r=self.client.post(path+'/payment',headers=headers,json={'quote_id':q2['quote_id']})
        self.assertEqual(r.status_code,200,r.text)

    def test_archived_product_is_not_hidden_by_cached_campaign(self):
        path,headers,_=self.configured();self.fake.archived=True
        r=self.client.post(path+'/quote',headers=headers,json={'contact':CONTACT,'shipping_id':2})
        self.assertEqual(r.status_code,502,r.text)
        self.assertEqual(self.fake.count('/authorize_payment'),0)

    def test_coupon_expiration_still_uses_live_sticky_result(self):
        attach_coupon(self.fake);path,headers,_=self.configured()
        body={'contact':CONTACT,'shipping_id':2,'coupon_code':'TEST99'}
        self.assertEqual(self.client.post(path+'/quote',headers=headers,json=body).status_code,200)
        self.fake.coupon_valid=False
        self.assertEqual(self.client.post(path+'/quote',headers=headers,json=body).status_code,422)
        self.assertEqual(self.fake.count('/authorize_payment'),0)

    def test_capture_rechecks_campaign_after_authorization_window(self):
        clock=[100];self.engine.state.capture_campaigns.clock=lambda:clock[0]
        path,headers,_,q=self.quoted()
        payment=self.client.post(path+'/payment',headers=headers,json={'quote_id':q['quote_id']}).json()
        self.fake.confirmed.add(payment['payment_intent_id']);self.fake.tax_provider=88;clock[0]=131
        r=self.client.post(path+'/complete',headers=headers,json={'payment_intent_id':payment['payment_intent_id']})
        self.assertEqual(r.status_code,409,r.text)
        self.assertEqual(self.fake.count('/new_order'),0)
