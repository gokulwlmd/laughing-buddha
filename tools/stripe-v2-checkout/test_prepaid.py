"""Prepaid money, cycle count and legacy boundaries; no external services."""
import copy
import unittest
import test_master as helpers
from test_checkout import CONTACT,ORIGIN
from fastapi.testclient import TestClient
from prepaid import cycles_for,configuration

class PrepaidTests(unittest.TestCase):
    setUp=helpers.MasterTests.setUp
    tearDown=helpers.MasterTests.tearDown
    post=helpers.MasterTests.post
    review=helpers.MasterTests.review
    apply=helpers.MasterTests.apply
    seed=helpers.MasterTests.seed
    provision=helpers.MasterTests.provision
    state=helpers.MasterTests.state
    # Inherit fixture helpers, not the standard suite's scenarios.
    def preset(self):return self.client.get('/api/admin/master-preset?prepaid=true').json()
    def setup_customer(self):
        self.seed();self.provision();link=self.state()['links'][0];customer=TestClient(self.app,base_url=ORIGIN);customer.get(link['url']);params={'link_id':link['id']};cfg=customer.get('/api/config',params=params).json();headers={'Origin':ORIGIN,'X-CSRF-Token':cfg['csrfToken'],'X-Checkout-Attempt':cfg['attemptId']}
        return customer,params,headers,cfg
    def test_prepaid_assignment_and_reapplication_keep_1200_total_300_unit_and_four_cycles(self):
        self.seed();self.provision();data=self.state();o=data['offers'][0]
        self.assertEqual(o['price'],'1200.00');self.assertEqual(self.fake.products[o['product_id']]['price'],300.0);self.assertEqual(cycles_for(self.fake.detail('/api/v2/offers/'+str(o['offer_id']))),4)
        self.provision();self.assertEqual(self.fake.count('/products'),1)
    def test_prepaid_total_and_owned_capture_include_cycle_count_and_stop_terms(self):
        c,p,h,cfg=self.setup_customer();o=cfg['options'][0];self.assertEqual(o['upfrontPrice'],'1200.0');self.assertEqual(o['prepaidCycles'],4);self.assertFalse(o['renewal'])
        q=c.post('/api/quote',params=p,headers=h,json={'contact':CONTACT,'selection':o['key'],'shipping_id':2});self.assertEqual(q.status_code,200,q.text);self.assertEqual(q.json()['amount'],120000)
        self.assertEqual(c.post('/api/authorize',params=p,headers=h,json={'quote_id':q.json()['id']}).status_code,422)
        a=c.post('/api/authorize',params=p,headers=h,json={'quote_id':q.json()['id'],'recurring_consent':True});self.assertEqual(a.status_code,200,a.text)
        self.fake.order_total='1200.00';cap=c.post('/api/capture',params=p,headers=h,json={});self.assertEqual(cap.status_code,200,cap.text)
        cap2=c.post('/api/capture',params=p,headers=h,json={});self.assertEqual(cap2.json(),cap.json());self.assertEqual(self.fake.count('/new_order'),1)
        line=next(b['offers'][0] for _,path,b in self.fake.calls if path=='/api/v1/new_order');self.assertEqual(line['prepaid_cycles'],4);self.assertEqual(line['quantity'],1);self.assertNotIn('price',line)
    def test_prepaid_invalid_price_and_models_rejected(self):
        for change in ({'price':'1200.01'},{'billing_models':[2]},{'billing_models':[3,4]},{'prepaid_cycles':1},{'prepaid_cycles':True}):
            d=self.preset();d['offers'][0].update(change);self.assertEqual(self.post('reviews',{'kind':'master','data':d}).status_code,422)
        self.assertEqual(self.fake.count('/products'),0)
    def test_physical_prepaid_can_be_saved_but_cannot_change_existing_campaign(self):
        d=self.client.get('/api/admin/master-preset').json()
        self.apply(self.review('master',d));self.apply(self.review('brand',{'id':'test-brand','name':'Test brand','campaign_id':422}));self.provision()
        before=self.state();calls=list(self.fake.calls)
        d['offers'].append(dict(self.preset()['offers'][0],id='prepaid-added'))
        review=self.review('master',d)
        self.assertIn('Campaign assignment is blocked',review['preview']['readinessNote'])
        self.assertEqual(review['preview']['stickyWrites'],[])
        self.assertEqual(self.apply(review).status_code,200)
        after=self.state();self.assertEqual(after['masters'][0]['offers'][0],before['masters'][0]['offers'][0])
        self.assertEqual(after['links'],before['links']);self.assertEqual(after['offers'],before['offers'])
        for kind,payload in [('provision',{'brand_id':'test-brand'}),('campaign_setup',{'brand_id':'test-brand','name':'Blocked prepaid campaign','template_id':422})]:
            r=self.post('reviews',{'kind':kind,'data':payload});self.assertEqual(r.status_code,422,r.text)
            self.assertIn('prepaid shipping and tax support',r.text)
        self.assertEqual(self.fake.calls,calls)
    def test_prepaid_source_becoming_taxable_blocks_assignment_before_writes(self):
        self.seed();original=self.fake.detail
        def changed(path):
            result=original(path)
            if path=='/api/v2/products/55098':result['taxable']=1
            return result
        self.fake.detail=changed
        r=self.post('reviews',{'kind':'provision','data':{'brand_id':'test-brand'}})
        self.assertEqual(r.status_code,422,r.text);self.assertIn('prepaid shipping and tax support',r.text)
        self.assertEqual(self.fake.count('/products'),0);self.assertEqual(self.fake.count('/offers'),0)
    def test_prepaid_tampered_quote_or_renewal_blocks_before_payment(self):
        c,p,h,cfg=self.setup_customer();offer=self.state()['offers'][0];self.fake.offers[offer['offer_id']]['prepaid']['is_subscription']=1
        q=c.post('/api/quote',params=p,headers=h,json={'contact':CONTACT,'selection':cfg['options'][0]['key'],'shipping_id':2});self.assertEqual(q.status_code,502);self.assertEqual(self.fake.count('/authorize_payment'),0)
    def test_prepaid_brand_price_replacement_preserves_terms(self):
        self.seed();self.provision();o=self.state()['offers'][0];d={k:o[k] for k in ('id','brand_id','sku','name','billing_models','configuration')};d['price']='1000.00';r=self.apply(self.review('offer',d));self.assertEqual(r.status_code,200,r.text);o=self.state()['offers'][0];self.assertEqual(self.fake.products[o['product_id']]['price'],250.0);self.provision();self.assertEqual(self.state()['offers'][0]['price'],'1000.00')
    def test_prepaid_unverified_terms_are_rejected(self):
        for mutate in ('conversion','discount','multiple','custom','expiry'):
            c=configuration(4)
            if mutate=='conversion':c['prepaid']['is_convert_to_standard']=1
            if mutate=='discount':c['prepaid']['terms'][0]['discount_value']=10
            if mutate=='multiple':c['prepaid']['terms'].append({'cycles':6,'discount_value':0})
            if mutate=='custom':c['recurring']['cycle_type_id']=2
            if mutate=='expiry':c['expire_cycles']=2
            with self.assertRaises(ValueError):cycles_for(c)


    def test_prepaid_wrong_quote_cycle_count_is_rejected_before_authorization(self):
        c,p,h,cfg=self.setup_customer();original=self.fake.call
        def altered(method,path,body=None):
            result=original(method,path,body)
            if path.endswith('/calculate'):result['data']['line_items'][0]['prepaid']['term']=3
            return result
        self.fake.call=altered
        q=c.post('/api/quote',params=p,headers=h,json={'contact':CONTACT,'selection':cfg['options'][0]['key'],'shipping_id':2});self.assertEqual(q.status_code,502);self.assertEqual(self.fake.count('/authorize_payment'),0)
    def test_prepaid_missing_capture_terms_holds_order_without_second_capture(self):
        c,p,h,cfg=self.setup_customer();q=c.post('/api/quote',params=p,headers=h,json={'contact':CONTACT,'selection':cfg['options'][0]['key'],'shipping_id':2}).json();a=c.post('/api/authorize',params=p,headers=h,json={'quote_id':q['id'],'recurring_consent':True});self.assertEqual(a.status_code,200)
        self.fake.order_total='1200.00';original=self.fake.call
        def altered(method,path,body=None):
            result=original(method,path,body)
            if path.endswith('/order_view'):result['products'][0].pop('prepaid',None)
            return result
        self.fake.call=altered
        self.assertEqual(c.post('/api/capture',params=p,headers=h,json={}).status_code,502);self.assertEqual(c.post('/api/capture',params=p,headers=h,json={}).status_code,409);self.assertEqual(self.fake.count('/new_order'),1)

    def test_renewing_prepaid_full_upfront_quote_capture_and_renewal_readback(self):
        for count,days in [(2,180),(4,360)]:
            with self.subTest(count=count):
                self.setUp()
                try:
                    d=self.preset();d['offers'][0].update(prepaid_cycles=count,prepaid_renewal=True)
                    self.apply(self.review('master',d));self.apply(self.review('brand',{'id':'test-brand','name':'Test brand','campaign_id':422}));self.provision()
                    link=self.state()['links'][0];customer=TestClient(self.app,base_url=ORIGIN);customer.get(link['url'])
                    params={'link_id':link['id']};cfg=customer.get('/api/config',params=params).json();o=cfg['options'][0]
                    self.assertTrue(o['renewal']);self.assertEqual(o['renewalDays'],days)
                    h={'Origin':ORIGIN,'X-CSRF-Token':cfg['csrfToken'],'X-Checkout-Attempt':cfg['attemptId']}
                    q=customer.post('/api/quote',params=params,headers=h,json={'contact':CONTACT,'selection':o['key'],'shipping_id':2}).json()
                    self.assertEqual(q['amount'],120000)
                    self.assertEqual(customer.post('/api/authorize',params=params,headers=h,json={'quote_id':q['id']}).status_code,422)
                    self.assertEqual(customer.post('/api/authorize',params=params,headers=h,json={'quote_id':q['id'],'recurring_consent':True}).status_code,200)
                    self.fake.order_total='1200.00'
                    self.assertEqual(customer.post('/api/capture',params=params,headers=h,json={}).status_code,200)
                    self.assertEqual(self.fake.count('/new_order'),1)
                    customer.close()
                finally:self.tearDown()

    def test_renewing_prepaid_capture_missing_renewal_is_held_without_retry(self):
        d=self.preset();d['offers'][0]['prepaid_renewal']=True
        self.apply(self.review('master',d));self.apply(self.review('brand',{'id':'test-brand','name':'Test brand','campaign_id':422}));self.provision()
        link=self.state()['links'][0];c=TestClient(self.app,base_url=ORIGIN);c.get(link['url']);params={'link_id':link['id']}
        cfg=c.get('/api/config',params=params).json();h={'Origin':ORIGIN,'X-CSRF-Token':cfg['csrfToken'],'X-Checkout-Attempt':cfg['attemptId']}
        q=c.post('/api/quote',params=params,headers=h,json={'contact':CONTACT,'selection':cfg['options'][0]['key'],'shipping_id':2}).json()
        c.post('/api/authorize',params=params,headers=h,json={'quote_id':q['id'],'recurring_consent':True})
        self.fake.order_total='1200.00';original=self.fake.call
        def changed(method,path,body=None):
            r=original(method,path,body)
            if path=='/api/v1/order_view':r['products'][0]['prepaid'][0]['is_renew']='0'
            return r
        self.fake.call=changed
        self.assertEqual(c.post('/api/capture',params=params,headers=h,json={}).status_code,502)
        self.assertEqual(c.post('/api/capture',params=params,headers=h,json={}).status_code,409)
        self.assertEqual(self.fake.count('/new_order'),1);c.close()
