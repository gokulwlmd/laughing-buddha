"""Same-authorization setup reuse; all financial reads/writes remain provider-bound."""
import copy
import unittest
from catalog import AuthorizationCampaignReuse
from test_site_session_api import SessionApiTests
from test_coupons import attach_coupon

class TicketTests(unittest.TestCase):
    def test_exact_attempt_campaign_quote_intent_one_use_and_expiry(self):
        now=[100];cache=AuthorizationCampaignReuse(clock=lambda:now[0]);value={'offers':[{'id':1}]}
        cache.remember('a',195,'q','pi',value,100);value['offers'].clear()
        self.assertIsNone(cache.consume('b',195,'q','pi'))
        self.assertTrue(cache.consume('a',195,'q','pi')['snapshot']['offers'])
        self.assertIsNone(cache.consume('a',195,'q','pi'))
        for args in [(422,'q','pi'),(195,'other','pi'),(195,'q','other')]:
            cache.remember('a',195,'q','pi',{'ok':True},100)
            self.assertIsNone(cache.consume('a',*args))
        cache.remember('a',195,'q','pi',{'ok':True},100);now[0]=130
        self.assertIsNone(cache.consume('a',195,'q','pi'))
        cache.remember('a',195,'q','pi',{'ok':True},100)
        self.assertFalse(cache.entries)

    def test_bounded_memory_discard_and_no_extension(self):
        now=[0];cache=AuthorizationCampaignReuse(clock=lambda:now[0],limit=2)
        for k in ('a','b','c'):cache.remember(k,1,'q','pi',{},0)
        self.assertEqual(list(cache.entries),['b','c']);cache.discard('b')
        now[0]=31;cache.remember('d',1,'q','pi',{},31)
        self.assertEqual(list(cache.entries),['d'])

class CaptureSpeedTests(unittest.TestCase):
    setUp=SessionApiTests.setUp
    tearDown=SessionApiTests.tearDown
    create=SessionApiTests.create
    configured=SessionApiTests.configured
    quoted=SessionApiTests.quoted
    prepared=SessionApiTests.prepared

    def prepare(self):
        path,headers,data,payment=self.prepared()
        self.fake.confirmed.add(payment['payment_intent_id'])
        self.fake.reads.clear()
        return path,headers,{'payment_intent_id':payment['payment_intent_id']}

    def test_immediate_capture_skips_only_campaign_and_keeps_all_selected_reads(self):
        path,headers,body=self.prepare()
        r=self.client.post(path+'/complete',headers=headers,json=body)
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['status'],'captured')
        self.assertFalse(any('/campaigns/' in p for p in self.fake.reads))
        for p in ('/api/v2/offers/706','/api/v2/products/54537','/api/v2/providers/payment/profiles/254'):
            self.assertIn(p,self.fake.reads)
        self.assertEqual(self.fake.count('/calculate'),3)
        self.assertEqual(self.fake.count('/new_order'),1);self.assertEqual(self.fake.count('/order_view'),1)
        self.assertFalse(self.engine.state.capture_campaigns.entries)
        self.client.post(path+'/complete',headers=headers,json=body)
        self.assertEqual(self.fake.count('/new_order'),1)

    def test_expired_ticket_rechecks_campaign_and_blocks_campaign_drift(self):
        clock=[100];self.engine.state.capture_campaigns.clock=lambda:clock[0]
        path,headers,body=self.prepare();clock[0]=130;self.fake.tax_provider=88
        r=self.client.post(path+'/complete',headers=headers,json=body)
        self.assertEqual(r.status_code,409,r.text);self.assertIn('/api/v2/campaigns/422',self.fake.reads)
        self.assertEqual(self.fake.count('/new_order'),0)

    def test_restart_or_missing_ticket_rechecks_full_campaign(self):
        path,headers,body=self.prepare();self.engine.state.capture_campaigns.entries.clear()
        r=self.client.post(path+'/complete',headers=headers,json=body)
        self.assertEqual(r.status_code,200,r.text);self.assertIn('/api/v2/campaigns/422',self.fake.reads)

    def test_resumed_form_disables_reuse(self):
        path,headers,body=self.prepare()
        r=self.client.post(path+'/resume',headers=headers,json={})
        self.assertEqual(r.status_code,200,r.text);self.fake.reads.clear()
        r=self.client.post(path+'/complete',headers=headers,json=body)
        self.assertEqual(r.status_code,200,r.text);self.assertIn('/api/v2/campaigns/422',self.fake.reads)

    def test_live_total_change_blocks_even_inside_window(self):
        path,headers,body=self.prepare();self.fake.total='3.00'
        r=self.client.post(path+'/complete',headers=headers,json=body)
        self.assertEqual(r.status_code,409,r.text);self.assertEqual(self.fake.count('/new_order'),0)

    def test_selected_product_offer_gateway_changes_block_inside_window(self):
        for change in ('product','offer','gateway'):
            with self.subTest(change=change):
                if change!='product':self.tearDown();self.setUp()
                path,headers,body=self.prepare();original=self.fake.detail
                def detail(p):
                    v=copy.deepcopy(original(p))
                    if change=='product' and '/products/' in p:v['price']='3.00'
                    if change=='offer' and '/offers/' in p:v['is_archived']=1
                    if change=='gateway' and '/profiles/' in p:v['fields']['account_fields']['publishable_key']='pk_live_changed'
                    return v
                self.fake.detail=detail
                r=self.client.post(path+'/complete',headers=headers,json=body)
                self.assertGreaterEqual(r.status_code,400,r.text);self.assertEqual(self.fake.count('/new_order'),0)

    def test_disabled_link_blocks_even_with_ticket(self):
        path,headers,body=self.prepare();admin=self.engine.state.admin
        link=admin.get('link',self.link_id);link['enabled']=False;admin.put('link',self.link_id,link)
        r=self.client.post(path+'/complete',headers=headers,json=body)
        self.assertGreaterEqual(r.status_code,400,r.text);self.assertEqual(self.fake.count('/new_order'),0)

    def test_authorize_is_still_forced_fresh_after_quote(self):
        path,headers,_,q=self.quoted();self.fake.reads.clear();self.fake.tax_provider=88
        r=self.client.post(path+'/payment',headers=headers,json={'quote_id':q['quote_id']})
        self.assertEqual(r.status_code,409,r.text);self.assertIn('/api/v2/campaigns/422',self.fake.reads)
        self.assertEqual(self.fake.count('/authorize_payment'),0)

    def test_window_expiring_during_price_check_forces_full_validation(self):
        clock=[100];self.engine.state.capture_campaigns.clock=lambda:clock[0]
        path,headers,body=self.prepare();original=self.fake.call
        def call(method,p,payload=None):
            if p.endswith('/calculate'):
                clock[0]=131;self.fake.tax_provider=88
            return original(method,p,payload)
        self.fake.call=call
        r=self.client.post(path+'/complete',headers=headers,json=body)
        self.assertEqual(r.status_code,409,r.text);self.assertIn('/api/v2/campaigns/422',self.fake.reads)
        self.assertEqual(self.fake.count('/new_order'),0)

    def test_coupon_failure_still_blocks_capture_inside_window(self):
        from test_checkout import CONTACT
        attach_coupon(self.fake)
        path,headers,_=self.configured()
        q=self.client.post(path+'/quote',headers=headers,json={'contact':CONTACT,'shipping_id':2,'coupon_code':'TEST99'}).json()
        payment=self.client.post(path+'/payment',headers=headers,json={'quote_id':q['quote_id']}).json()
        self.fake.confirmed.add(payment['payment_intent_id']);self.fake.coupon_valid=False
        r=self.client.post(path+'/complete',headers=headers,json={'payment_intent_id':payment['payment_intent_id']})
        self.assertEqual(r.status_code,502,r.text);self.assertEqual(self.fake.count('/new_order'),0)

    def test_uncertain_order_is_never_repeated(self):
        path,headers,body=self.prepare();original=self.fake.call
        def call(method,p,payload=None):
            result=original(method,p,payload)
            if p.endswith('/new_order'):
                from app import StickyError
                raise StickyError('Lost reply')
            return result
        self.fake.call=call
        self.assertEqual(self.client.post(path+'/complete',headers=headers,json=body).status_code,502)
        self.assertGreaterEqual(self.client.post(path+'/complete',headers=headers,json=body).status_code,400)
        self.assertEqual(self.fake.count('/new_order'),1)
