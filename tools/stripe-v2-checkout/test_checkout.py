"""Offline financial-boundary tests. No external payment requests."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from app import Settings, StickyError, Store, create_app

CONTACT = {'name':'Checkout Tester','email':'checkout@example.com','phone':'+12025550100',
    'address':'1 Test Way','city':'San Francisco','region':'CA','postal_code':'94105','country':'US'}
ORIGIN='https://checkout.example'
SKU='WLMD-CORE-2USD-0f89b1bb'

class FakeSticky:
    def __init__(self):
        self.calls=[];self.reads=[];self.fail_authorize=False;self.capture_code='100';self.total='2.00'
        self.secret_intent='pi_owned123';self.order_total='2.00';self.link_gateway=254;self.archived=False;self.missing=False;self.duplicate=False
        self.recurring=False;self.prepaid=False;self.key='pi_owned123';self.tax_provider=0
    def offer(self):
        return {'id':706,'name':'Configured offer','is_prepaid':int(self.prepaid),
            'products':[{'id':54537}]+([{'id':54538}] if self.duplicate else []),
            'billing_models':[{'id':2,'name':'One time'}]+([{'id':3,'name':'30 days','days':30,'type':{'id':1}}] if self.recurring else [])}
    def detail(self,path):
        self.reads.append(path)
        if path=='/api/v2/offers/706':return self.offer()
        if '/campaigns/' in path:
            return {'name':'Any brand','is_active':1,'is_archived':0,'gateway_id':99,'tax_provider_id':self.tax_provider,
                'payment_methods':[{'value':'visa'},{'value':'stripe_link'},{'value':'master'}],
                'alternative_payments':[{'payment_method':'stripe_link','provider':{'id':self.link_gateway,'account_id':250}}],
                'offers':[self.offer()],
                'shipping_profiles':[{'id':2,'name':'Free shipping'}],'countries':[{'iso_2':'US','name':'United States'}]}
        if '/products/' in path:
            return {'id':int(path.split('/')[-1]),'name':'SKU product','sku':'OTHER' if self.missing else SKU,
                'price':'2.00','is_shippable':0,'taxable':1,'archived_flag':int(self.archived)}
        if '/profiles/' in path:
            return {'account_id':250,'currency':{'code':'USD'},'fields':{'account_fields':{
                'publishable_key':'pk_live_placeholder','access_token':'NEVER_EXPOSE_THIS','capture_on_shipment':False}}}
        raise AssertionError(path)
    def call(self,method,path,body=None):
        self.calls.append((method,path,copy.deepcopy(body)))
        if path.endswith('/calculate'):
            return {'status':'SUCCESS','data':{'total':self.total,'line_items':[{'id':body['offers'][0]['product_id'],'qty':1}]}}
        if path.endswith('/authorize_payment'):
            if self.fail_authorize: raise StickyError('Uncertain authorization')
            return {'response_code':'100','digitalWalletToken':self.secret_intent+'_secret_private123','transactionID':self.key}
        if path.endswith('/new_order'):
            return {'response_code':self.capture_code,'order_id':str(900000+self.count('/new_order'))}
        if path.endswith('/order_view'):
            payload=next(b for _,p,b in reversed(self.calls) if p.endswith('/new_order'));o=payload['offers'][0]
            return {'response_code':'100','order_status':'2','order_total':self.order_total,'gateway_id':'254',
                'campaign_id':str(payload['campaignId']),'products':[{'product_id':str(o['product_id']),
                    'billing_model':{'id':str(o['billing_model_id'])},'product_qty':'1','offer':{'id':str(o['offer_id'])},
                    'is_recurring':'0' if o['billing_model_id']==2 else '1'}]}
        raise AssertionError(path)
    def count(self,suffix): return sum(p.endswith(suffix) for _,p,_ in self.calls)

class CheckoutTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.fake=FakeSticky()
        self.settings=Settings(public_url=ORIGIN,state_dir=Path(self.temp.name),authorization_verified=True)
        self.app=create_app(self.settings,self.fake);self.client=TestClient(self.app,base_url=ORIGIN)
        self.client.get('/?access='+self.app.state.invite)
        self.params={'campaign_id':422,'sku':SKU}
        self.config=self.client.get('/api/config',params=self.params).json()
        self.headers={'Origin':ORIGIN,'X-CSRF-Token':self.config['csrfToken'],'X-Checkout-Attempt':self.config['attemptId']}
    def tearDown(self): self.client.close();self.temp.cleanup()
    def post(self,path,body): return self.client.post('/api/'+path,params=self.params,headers=self.headers,json=body)
    def quote(self,selection='706:54537:2'):
        return self.post('quote',{'contact':CONTACT,'selection':selection,'shipping_id':2})
    def authorize(self,consent=False,selection='706:54537:2'):
        q=self.quote(selection);self.assertEqual(q.status_code,200,q.text)
        return self.post('authorize',{'quote_id':q.json()['id'],'recurring_consent':consent})
    def capture(self): return self.post('capture',{})
    def test_access_origin_and_card_input_rejected(self):
        outsider=TestClient(self.app,base_url=ORIGIN)
        self.assertEqual(outsider.get('/api/config').status_code,401)
        self.assertEqual(self.client.post('/api/quote',json={'contact':CONTACT,'selection':'706:54537:2'}).status_code,403)
        r=self.post('quote',{'contact':CONTACT|{'creditCardNumber':'4242424242424242'},'selection':'706:54537:2'})
        self.assertEqual(r.status_code,422);self.assertNotIn('424242',r.text)
    def test_arbitrary_campaign_resolves_and_scopes_product_reads(self):
        self.client.get('/checkout/987/'+SKU);self.params['campaign_id']=987
        c=self.client.get('/api/config',params=self.params)
        self.assertEqual(c.status_code,200);self.assertEqual(c.json()['campaignId'],987)
        self.assertTrue(all('/products/' not in p or p.endswith('/54537') for p in self.fake.reads))
        self.assertNotIn('NEVER_EXPOSE_THIS',c.text)
    def test_unknown_or_archived_sku_rejected(self):
        self.fake.missing=True;self.assertEqual(self.quote().status_code,502)
        self.fake.missing=False;self.fake.archived=True;self.assertEqual(self.quote().status_code,502)
        self.assertEqual(self.fake.count('/authorize_payment'),0)
    def test_duplicate_sku_retains_explicit_product_choices(self):
        self.fake.duplicate=True
        c=self.client.get('/api/config',params=self.params).json()
        self.assertEqual(len(c['options']),2)
        self.assertEqual(self.quote('706:999:2').status_code,502)
    def test_quote_and_authorize_preserve_server_price_and_tax(self):
        self.fake.tax_provider=88;self.fake.total='2.25'
        self.assertEqual(self.authorize().status_code,200)
        body=next(b for _,p,b in self.fake.calls if p.endswith('/authorize_payment'))
        self.assertEqual(body['auth_amount'],'2.25');self.assertEqual(body['forceGatewayId'],254)
        self.assertEqual(body['billingCountry'],'US');self.assertNotIn('amount',body)
        q=next(b for _,p,b in self.fake.calls if p.endswith('/calculate'))
        self.assertEqual(q['use_tax_provider'],1);self.assertNotIn('price',q['offers'][0])
        self.assertNotIn('private123',(Path(self.temp.name)/'checkout.sqlite3').read_bytes().decode(errors='ignore'))
    def test_price_or_gateway_changed_after_quote_blocks_authorization(self):
        q=self.quote().json();self.fake.total='3.00'
        r=self.post('authorize',{'quote_id':q['id']});self.assertEqual(r.status_code,409)
        self.assertEqual(self.fake.count('/authorize_payment'),0)
    def test_unrelated_offer_shipping_or_amount_injection_rejected(self):
        self.assertEqual(self.quote('999:54537:2').status_code,502)
        self.assertEqual(self.post('quote',{'contact':CONTACT,'selection':'706:54537:2','shipping_id':99}).status_code,502)
        self.assertEqual(self.post('authorize',{'quote_id':'x','amount':1}).status_code,422)
        self.assertEqual(self.post('capture',{'transactionId':'pi_attacker'}).status_code,422)
    def test_recurring_requires_explicit_consent(self):
        self.fake.recurring=True
        self.assertEqual(self.authorize(selection='706:54537:3').status_code,422)
        self.assertEqual(self.fake.count('/authorize_payment'),0)
        self.assertEqual(self.authorize(consent=True,selection='706:54537:3').status_code,200)
        self.assertEqual(self.capture().status_code,200)
    def test_capture_uses_owned_intent_preserves_rules_and_cannot_repeat(self):
        self.assertEqual(self.authorize().status_code,200)
        r=self.capture();self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json(),self.capture().json());self.assertEqual(self.fake.count('/new_order'),1)
        b=next(b for _,p,b in self.fake.calls if p.endswith('/new_order'))
        self.assertEqual(b['transactionId'],'pi_owned123');self.assertEqual(b['tranType'],'Capture')
        self.assertNotIn('price',b['offers'][0]);self.assertEqual(b['three_d_redirect_url'],ORIGIN+'/checkout/422/'+SKU)
    def test_uncertain_authorization_is_held_across_restart(self):
        self.fake.fail_authorize=True;self.assertEqual(self.authorize().status_code,502)
        self.assertEqual(self.post('authorize',{'quote_id':'anything'}).status_code,409)
        self.assertEqual(Store(Path(self.temp.name)).read(self.headers['X-Checkout-Attempt'])['status'],'authorization_pending')
        self.assertEqual(self.fake.count('/authorize_payment'),1)
    def test_mismatched_intent_is_held(self):
        self.fake.key='pi_other';self.assertEqual(self.authorize().status_code,502)
        self.assertEqual(self.capture().status_code,409);self.assertEqual(self.fake.count('/new_order'),0)
    def test_route_change_after_authorization_blocks_capture(self):
        self.authorize();self.fake.link_gateway=165
        self.assertEqual(self.capture().status_code,409);self.assertEqual(self.fake.count('/new_order'),0)
    def test_unexpected_total_or_3ds_cannot_repeat_capture(self):
        self.authorize();self.fake.order_total='9.00'
        self.assertEqual(self.capture().status_code,502);self.assertEqual(self.capture().status_code,409)
        self.assertEqual(self.fake.count('/new_order'),1)
    def test_response_101_held_for_reconciliation(self):
        self.authorize();self.fake.capture_code='101'
        self.assertEqual(self.capture().status_code,502);self.assertEqual(self.capture().status_code,409)
        self.assertEqual(self.fake.count('/new_order'),1)
    def test_unsupported_offer_resolves_but_does_not_silently_change_rules(self):
        self.fake.prepaid=True
        c=self.client.get('/api/config',params=self.params).json();self.assertIn('prepaid',c['options'][0]['blockedReason'])
        self.assertEqual(self.quote().status_code,502);self.assertEqual(self.fake.count('/authorize_payment'),0)
    def test_two_browser_sessions_are_isolated_for_same_campaign_sku(self):
        self.client.get('/checkout/987/'+SKU);self.params['campaign_id']=987
        self.headers['X-Checkout-Attempt']=self.client.get('/api/status',params=self.params).json()['attemptId']
        self.authorize()
        other=TestClient(self.app,base_url=ORIGIN);other.cookies.set('checkout_access',self.app.state.invite)
        other.get('/checkout/987/'+SKU)
        s=other.get('/api/status',params=self.params).json();self.assertEqual(s['status'],'new');self.assertIsNone(s['intentId'])
        self.assertEqual(self.client.get('/api/status',params=self.params).json()['status'],'awaiting_card')
    def test_legacy_paid_receipt_migrates_without_reset(self):
        with tempfile.TemporaryDirectory() as d:
            st=Store(Path(d))
            with st.db() as db:
                db.execute("DELETE FROM checkouts WHERE id='legacy'")
                db.execute("UPDATE purchase SET status='captured',order_id='505015' WHERE id=1")
            migrated=Store(Path(d));self.assertEqual(migrated.read()['order_id'],'505015')
            self.assertFalse(migrated.claim('new','authorization_pending'))
    def test_same_link_can_buy_again_with_distinct_payment_and_preserved_receipt(self):
        self.assertEqual(self.authorize().status_code,200)
        first=self.capture().json()
        previous=self.headers['X-Checkout-Attempt']
        restarted=self.post('new-purchase',{'previous_attempt_id':previous})
        self.assertEqual(restarted.status_code,200,restarted.text)
        next_id=restarted.json()['attemptId'];self.assertNotEqual(next_id,previous)
        self.assertEqual(self.app.state.store.read(previous)['order_id'],first['orderId'])
        row=self.app.state.store.read(next_id)
        self.assertEqual(row['status'],'new');self.assertIsNone(row['intent_id']);self.assertIsNone(row['contact'])
        self.headers['X-Checkout-Attempt']=next_id
        self.client.get('/checkout/422/'+SKU)
        self.fake.key=self.fake.secret_intent='pi_second123'
        self.assertEqual(self.authorize().status_code,200)
        second=self.capture().json()
        self.assertNotEqual(first['orderId'],second['orderId'])
        self.assertEqual(self.fake.count('/new_order'),2)
        self.assertEqual(self.capture().json(),second)
        self.assertEqual(self.fake.count('/new_order'),2)
        self.assertEqual(self.app.state.store.read(previous)['order_id'],first['orderId'])
        self.assertEqual(self.app.state.store.read(next_id)['intent_id'],'pi_second123')

    def test_new_purchase_double_click_and_response_retry_reuse_one_successor(self):
        self.authorize();self.capture()
        body={'previous_attempt_id':self.headers['X-Checkout-Attempt']}
        first=self.post('new-purchase',body);second=self.post('new-purchase',body)
        self.assertEqual(first.status_code,200);self.assertEqual(first.json(),second.json())
        with self.app.state.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM checkouts WHERE id<>\'legacy\'').fetchone()[0],2)
        self.assertEqual(self.fake.count('/authorize_payment'),1)
        self.assertEqual(self.fake.count('/new_order'),1)

    def test_open_or_uncertain_attempt_cannot_be_replaced(self):
        previous=self.headers['X-Checkout-Attempt']
        self.assertEqual(self.post('new-purchase',{'previous_attempt_id':previous}).status_code,409)
        self.authorize()
        self.assertEqual(self.post('new-purchase',{'previous_attempt_id':previous}).status_code,409)
        self.fake.capture_code='101';self.capture()
        self.assertEqual(self.post('new-purchase',{'previous_attempt_id':previous}).status_code,409)
        with self.app.state.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM checkouts WHERE id<>\'legacy\'').fetchone()[0],1)

    def test_stale_tab_cannot_quote_authorize_or_capture_the_new_purchase(self):
        self.authorize();self.capture()
        self.post('new-purchase',{'previous_attempt_id':self.headers['X-Checkout-Attempt']})
        self.assertEqual(self.quote().status_code,409)
        self.assertEqual(self.post('authorize',{'quote_id':'old'}).status_code,409)
        self.assertEqual(self.capture().status_code,409)
        self.assertEqual(self.client.get('/api/status',params=self.params,headers=self.headers).status_code,409)
        self.assertEqual(self.fake.count('/new_order'),1)

    def test_restart_requires_private_access_csrf_and_matching_previous_attempt(self):
        self.authorize();self.capture()
        self.assertEqual(self.post('new-purchase',{'previous_attempt_id':'other'}).status_code,409)
        self.assertEqual(self.client.post('/api/new-purchase',params=self.params,
            json={'previous_attempt_id':'legacy'}).status_code,403)
        outsider=TestClient(self.app,base_url=ORIGIN)
        self.assertEqual(outsider.post('/api/new-purchase',json={'previous_attempt_id':'legacy'}).status_code,401)

    def test_first_visit_to_default_link_is_fresh_and_does_not_show_other_receipts(self):
        self.authorize();self.capture()
        other=TestClient(self.app,base_url=ORIGIN)
        other.get('/?access='+self.app.state.invite)
        status=other.get('/api/status',params=self.params).json()
        self.assertEqual(status['status'],'new');self.assertIsNone(status['orderId'])
        self.assertNotEqual(status['attemptId'],self.headers['X-Checkout-Attempt'])

    def test_original_legacy_receipt_can_start_a_separate_purchase(self):
        self.app.state.store.claim('new','captured',order_id='505015')
        name=next(c.name for c in self.client.cookies.jar if c.name.startswith('purchase_'))
        self.client.cookies.set(name,'legacy',domain='checkout.example',path='/')
        self.headers['X-Checkout-Attempt']='legacy'
        restarted=self.post('new-purchase',{'previous_attempt_id':'legacy'})
        self.assertEqual(restarted.status_code,200,restarted.text)
        self.assertNotEqual(restarted.json()['attemptId'],'legacy')
        self.assertEqual(self.app.state.store.read()['order_id'],'505015')

    def test_new_purchase_survives_restart_and_keeps_previous_receipt(self):
        self.authorize();self.capture()
        previous=self.headers['X-Checkout-Attempt']
        new_id=self.post('new-purchase',{'previous_attempt_id':previous}).json()['attemptId']
        restored=Store(Path(self.temp.name))
        self.assertEqual(restored.read(previous)['status'],'captured')
        self.assertEqual(restored.read(new_id)['status'],'new')
        self.assertEqual(restored.start_next(previous),new_id)

    def test_unverified_contract_blocks_financial_writes(self):
        self.settings.authorization_verified=False
        self.assertEqual(self.authorize().status_code,503);self.assertEqual(self.fake.count('/authorize_payment'),0)

if __name__=='__main__': unittest.main()
