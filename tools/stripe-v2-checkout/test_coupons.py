"""Offline discount, consent and capture boundaries."""
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from app import ROUTE_LOCK
from catalog import quote, CatalogError
from demo.session_api import terms
import test_checkout as checkout_tests
import test_site_session_api as session_tests
CONTACT=checkout_tests.CONTACT

def attach_coupon(fake):
    old_detail,old_call=fake.detail,fake.call
    fake.coupon_lifetime=True;fake.coupon_valid=True;fake.coupon_assigned=True;fake.coupon_order_id='123'
    def detail(path):
        if path=='/api/v2/coupons/123':
            return {'id':123,'type_id':1,'name':'TEST99','discount_percent':'99.00','is_lifetime':int(fake.coupon_lifetime),'is_active':1,'promo_codes':[{'code':'TEST99','is_active':1,'is_deleted':0}]}
        result=old_detail(path)
        if '/campaigns/' in path:result['coupon_profiles']=[{'id':123,'name':'TEST99'}] if fake.coupon_assigned else []
        return result
    def call(method,path,body=None):
        result=old_call(method,path,body)
        if path.endswith('/calculate') and body.get('promo'):
            result['data'].update(total='0.02',discounts=[{'type':'promo','code':body['promo']['code'],'valid':fake.coupon_valid,'total':'1.98'}])
        if path.endswith('/order_view'):
            result.update(order_total='0.02',coupon_id=fake.coupon_order_id,coupon_discount_amount='1.98')
        return result
    fake.detail,fake.call=detail,call

class CouponTests(unittest.TestCase):
    setUp=checkout_tests.CheckoutTests.setUp
    tearDown=checkout_tests.CheckoutTests.tearDown
    post=checkout_tests.CheckoutTests.post
    capture=checkout_tests.CheckoutTests.capture
    def discounted(self,recurring=False):
        attach_coupon(self.fake);self.fake.recurring=recurring
        return self.post('quote',{'contact':CONTACT,'selection':'706:54537:'+('3' if recurring else '2'),'shipping_id':2,'coupon_code':'TEST99'})
    def test_discount_is_quoted_by_sticky_and_carried_to_capture(self):
        q=self.discounted();self.assertEqual(q.status_code,200,q.text)
        self.assertEqual(q.json()['amount'],2);self.assertEqual(q.json()['discountAmount'],198)
        auth=self.post('authorize',{'quote_id':q.json()['id']});self.assertEqual(auth.status_code,200,auth.text)
        self.assertEqual(self.capture().status_code,200);self.assertEqual(self.capture().status_code,200)
        requests=[b for _,p,b in self.fake.calls if p.endswith('/calculate')]
        self.assertTrue(all(b['promo']=={'code':'TEST99','email':CONTACT['email']} for b in requests))
        auth=next(b for _,p,b in self.fake.calls if p.endswith('/authorize_payment'));self.assertEqual(auth['auth_amount'],'0.02')
        capture=next(b for _,p,b in self.fake.calls if p.endswith('/new_order'));self.assertEqual(capture['promoCode'],'TEST99')
        self.assertNotIn('price',capture['offers'][0]);self.assertEqual(self.fake.count('/new_order'),1)
    def test_other_campaign_and_expired_coupon_do_not_fall_back_to_full_price(self):
        self.discounted();self.fake.coupon_assigned=False
        body={'contact':CONTACT,'selection':'706:54537:2','shipping_id':2,'coupon_code':'TEST99'}
        self.assertEqual(self.post('quote',body).status_code,422)
        self.fake.coupon_assigned=True;self.fake.coupon_valid=False
        self.assertEqual(self.post('quote',body).status_code,422);self.assertEqual(self.fake.count('/authorize_payment'),0)
    def test_changed_renewal_invalidates_consent_with_same_initial_total(self):
        q=self.discounted(True).json();self.fake.coupon_lifetime=False
        self.assertEqual(self.post('authorize',{'quote_id':q['id'],'recurring_consent':True}).status_code,409)
        self.assertEqual(self.fake.count('/authorize_payment'),0)
    def test_recurring_readback_must_match(self):
        q=self.discounted(True).json()
        self.assertEqual(self.post('authorize',{'quote_id':q['id'],'recurring_consent':True}).status_code,200)
        self.fake.coupon_order_id='999'
        self.assertEqual(self.capture().status_code,502);self.assertEqual(self.capture().status_code,409)
        self.assertEqual(self.fake.count('/new_order'),1)
    def test_first_only_coupon_preserves_full_renewal(self):
        self.discounted(True);self.fake.coupon_lifetime=False
        q=self.post('quote',{'contact':CONTACT,'selection':'706:54537:3','shipping_id':2,'coupon_code':'TEST99'}).json()
        self.assertEqual(q['renewalPrice'],'2.00')
        self.assertEqual(self.post('authorize',{'quote_id':q['id'],'recurring_consent':True}).status_code,200)
        self.assertEqual(self.capture().status_code,200)
    def test_client_discount_amount_rejected(self):
        self.assertEqual(self.post('quote',{'contact':CONTACT,'selection':'706:54537:2','discount_percent':99}).status_code,422)

    def test_quote_network_wait_does_not_hold_global_payment_lock(self):
        entered=threading.Event();release=threading.Event();previous=self.fake.call
        def delayed(method,path,body=None):
            if path.endswith('/calculate'):
                entered.set();release.wait(3)
            return previous(method,path,body)
        self.fake.call=delayed
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(self.post,'quote',{'contact':CONTACT,'selection':'706:54537:2','shipping_id':2})
            try:
                self.assertTrue(entered.wait(3))
                acquired=ROUTE_LOCK.acquire(timeout=.5)
                if acquired:ROUTE_LOCK.release()
                self.assertTrue(acquired)
                # A payment begun while this read was in flight prevents the
                # quote from replacing either its contact or its stored quote.
                self.app.state.store.claim('new','authorization_pending',self.config['attemptId'])
            finally:release.set()
            self.assertEqual(future.result().status_code,409)
        row=self.app.state.store.read(self.config['attemptId'])
        self.assertIsNone(row['contact']);self.assertIsNone(row['quote'])

    def test_prepaid_discount_keeps_full_term_and_rounds_renewal(self):
        class API:
            cycles=2
            def detail(self,path):
                return {'id':123,'type_id':1,'discount_percent':'99.00','is_lifetime':1,'is_active':1,
                        'promo_codes':[{'code':'TEST99','is_active':1,'is_deleted':0}]}
            def call(self,method,path,body):
                return {'data':{'total':'10.15','line_items':[{'id':1,'qty':1,'is_prepaid':True,
                    'prepaid':{'term':self.cycles,'total':'1014.90'}}],
                    'discounts':[{'type':'promo','code':'TEST99','valid':True,'total':'1004.75'}]}}
        option={'key':'1:1:3','productId':1,'offerId':1,'billingModelId':3,'blockedReason':'','shippable':True,
                'prepaidCycles':2,'upfrontPrice':'1014.90','basePrice':'507.45','recurring':True,'days':90,'renewal':True,'renewalDays':180}
        catalog={'options':[option],'blockedReason':'','countries':[{'code':'US'}],'shipping':[{'id':2}],
                 'campaignId':195,'currency':'usd','sku':'SEMA-6M-SUB','gatewayId':269,'fingerprint':'same',
                 'couponProfiles':[{'id':123,'name':'TEST99'}]}
        api=API();q=quote(api,catalog,'1:1:3',2,CONTACT,'TEST99')
        self.assertEqual((q['amount'],q['renewalPrice'],q['option']['prepaidCycles']),(1015,'10.15',2))
        api.cycles=4
        with self.assertRaises(CatalogError):quote(api,catalog,'1:1:3',2,CONTACT,'TEST99')

    def test_other_cart_order_coupon_usage_does_not_invalidate_quote(self):
        q=self.discounted().json();previous=self.fake.detail
        def changed(path):
            value=previous(path)
            if '/campaigns/' in path:value['coupon_profiles'][0]['use_count']=1
            return value
        self.fake.detail=changed
        self.assertEqual(self.post('authorize',{'quote_id':q['id']}).status_code,200)

class CouponApiTests(unittest.TestCase):
    setUp=session_tests.SessionApiTests.setUp
    tearDown=session_tests.SessionApiTests.tearDown
    create=session_tests.SessionApiTests.create
    configured=session_tests.SessionApiTests.configured
    def test_public_api_discount_contract(self):
        attach_coupon(self.fake);path,headers,_=self.configured()
        r=self.client.post(path+'/quote',headers=headers,json={'contact':CONTACT,'shipping_id':2,'coupon_code':'TEST99'})
        self.assertEqual(r.status_code,200,r.text);q=r.json()
        self.assertEqual((q['coupon_code'],q['discount_amount'],q['subtotal_amount'],q['amount']),('TEST99',198,200,2))
        self.assertTrue(q['discount_applies_to_renewals']);self.assertNotIn('profileId',r.text)
    def test_explicit_renewal_amount(self):
        q={'amount':1428,'currency':'usd','renewalPrice':'14.28','option':{'recurring':True,'prepaidCycles':4,'days':90,'renewal':True,'renewalDays':360,'upfrontPrice':'1428'}}
        self.assertIn('14.28 USD every 360 days',terms(q));self.assertIn('4 deliveries',terms(q))
