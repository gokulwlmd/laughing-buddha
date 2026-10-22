"""Real API facade against the existing payment engine with fake Sticky only."""
import copy
from http.cookies import SimpleCookie
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app import create_app,Settings
from plans import choice_id
from test_checkout import FakeSticky,CONTACT
from test_site_api_public import fixture
from demo.public import create_public_app,PUBLISHED_PLAN
from demo.session_api import SessionStore,CheckoutTransport,UpstreamError,PUBLIC_UPSTREAM

ORIGIN='https://api.example'
BASE='/api/v1/sites/payment-test/sessions'

class PaymentFake(FakeSticky):
    def __init__(self):
        super().__init__();self.confirmed=set()
    def detail(self,path):
        value=super().detail(path)
        if '/products/' in path:value['sku']='SEMA-1M'
        return value
    def call(self,method,path,body=None):
        if path.endswith('/new_order') and body['transactionId'] not in self.confirmed:
            self.calls.append((method,path,copy.deepcopy(body)))
            return {'response_code':'10800'}
        return super().call(method,path,body)

class EngineTransport:
    def __init__(self,backend):
        self.backend=backend;self.calls=[];self.fail_before=None;self.fail_after=None
    def call(self,row,method,path,body=None,client_ip=None):
        self.calls.append((method,path,copy.deepcopy(body),row['attempt']))
        if path==self.fail_before:
            self.fail_before=None;raise UpstreamError()
        cookies=json.loads(row['cookies'])
        headers={'Cookie':'; '.join(k+'='+v for k,v in cookies.items()),'Origin':PUBLIC_UPSTREAM,'X-CSRF-Token':row['csrf']}
        if row['attempt']:headers['X-Checkout-Attempt']=row['attempt']
        params={'link_id':row['link_id']} if path.startswith('/api/') else None
        with TestClient(self.backend,base_url=PUBLIC_UPSTREAM) as client:
            response=client.request(method,path,params=params,headers=headers,json=body)
        if path==self.fail_after:
            self.fail_after=None;raise UpstreamError()
        if response.status_code>=400:
            raise UpstreamError(response.status_code,response.json().get('detail','Rejected'))
        for value in response.headers.get_list('set-cookie'):
            parsed=SimpleCookie();parsed.load(value)
            cookies.update({k:v.value for k,v in parsed.items()})
        return (response.text if path.startswith('/c/') else response.json()),cookies

class SessionApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.now=1000
        self.fake=PaymentFake()
        self.engine=create_app(Settings(public_url=PUBLIC_UPSTREAM,state_dir=self.root/'upstream',authorization_verified=True),self.fake)
        self.link_id=choice_id(PUBLISHED_PLAN,'SEMA-1M','plan-1')
        self.engine.state.admin.put('brand','api-brand',{'id':'api-brand','name':'API Brand','campaign_id':422,'color':'#245844'})
        self.engine.state.admin.put('link',self.link_id,{'id':self.link_id,'brand_id':'api-brand','campaign_id':422,'sku':'SEMA-1M',
            'options':['706:54537:2'],'visibility':'public','enabled':True,'revision':1,'title':'API payment test','payment_test_only':True})
        self.store=SessionStore(self.root/'sessions',clock=lambda:self.now)
        self.transport=EngineTransport(self.engine)
        self.catalog=fixture()
        self.catalog['entries'][0]['options'][0]['key']='706:54537:2'
        self.api=create_public_app(ORIGIN,read_catalog=lambda catalog:self.catalog,session_store=self.store,transport=self.transport)
        self.client=TestClient(self.api,base_url=ORIGIN)

    def tearDown(self):
        self.client.close();self.temp.cleanup()

    def create(self):
        response=self.client.post(BASE,json={'plan_id':'sema-1m'})
        self.assertEqual(response.status_code,201,response.text)
        data=response.json();headers={'Authorization':'Bearer '+data['session_token']}
        return BASE+'/'+data['session_id'],headers,data

    def configured(self):
        path,headers,data=self.create()
        response=self.client.get(path+'/configuration',headers=headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertNotIn('csrf',response.text.lower());self.assertNotIn('attemptId',response.text)
        return path,headers,data

    def quoted(self):
        path,headers,data=self.configured()
        response=self.client.post(path+'/quote',headers=headers,json={'contact':CONTACT,'shipping_id':2})
        self.assertEqual(response.status_code,200,response.text)
        return path,headers,data,response.json()

    def prepared(self):
        path,headers,data,q=self.quoted()
        response=self.client.post(path+'/payment',headers=headers,json={'quote_id':q['quote_id'],'accept_terms':False})
        self.assertEqual(response.status_code,200,response.text)
        return path,headers,data,response.json()

    def test_full_on_page_contract_and_idempotent_completion(self):
        path,headers,data,payment=self.prepared()
        self.assertNotIn('checkout_url',data)
        self.assertEqual(payment['amount'],200)
        self.assertEqual(payment['payment_intent_id'],self.fake.key)
        self.fake.confirmed.add(payment['payment_intent_id'])
        body={'payment_intent_id':payment['payment_intent_id']}
        first=self.client.post(path+'/complete',headers=headers,json=body)
        again=self.client.post(path+'/complete',headers=headers,json=body)
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(first.json()['status'],'captured');self.assertEqual(first.json(),again.json())
        self.assertEqual(self.fake.count('/authorize_payment'),1);self.assertEqual(self.fake.count('/new_order'),1)
        self.assertEqual(self.client.get(path,headers=headers).json()['status'],'captured')

    def test_session_tokens_isolate_same_plan_and_expire_without_resetting_attempt(self):
        a,ha,da=self.create();b,hb,db=self.create()
        self.assertNotEqual(da['session_token'],db['session_token'])
        ra=self.store.read(da['session_id']);rb=self.store.read(db['session_id'])
        self.assertNotEqual(ra['attempt'],rb['attempt']);self.assertNotEqual(ra['cookies'],rb['cookies'])
        self.assertEqual(self.client.get(a,headers=hb).status_code,401)
        self.assertEqual(self.client.get(b,headers=ha).status_code,401)
        self.assertEqual(self.client.get(a).status_code,401)
        self.now+=86401
        self.assertEqual(self.client.get(a,headers=ha).status_code,410)
        self.assertEqual(self.engine.state.store.read(ra['attempt'])['status'],'new')

    def test_rejects_arbitrary_amount_route_intent_and_raw_card_fields_without_echo(self):
        path,headers,data,q=self.quoted()
        for key in ('amount','gateway_id','campaign_id','selection','client_secret','card_number'):
            response=self.client.post(path+'/payment',headers=headers,json={'quote_id':q['quote_id'],key:'DO_NOT_ECHO'})
            self.assertEqual(response.status_code,422);self.assertNotIn('DO_NOT_ECHO',response.text)
        response=self.client.post(path+'/quote',headers=headers,json={'contact':CONTACT|{'card_number':'DO_NOT_ECHO'}})
        self.assertEqual(response.status_code,422);self.assertNotIn('DO_NOT_ECHO',response.text)
        self.assertEqual(self.client.post(path+'/complete',headers=headers,json={'payment_intent_id':'pi_wrong'}).status_code,409)
        self.assertEqual(self.fake.count('/new_order'),0)
        self.assertEqual(self.client.post(BASE,json={'plan_id':'sema-1m','checkout_url':'https://evil.example'}).status_code,422)
        self.assertEqual(self.client.post(BASE,json={'plan_id':'not-published'}).status_code,404)

    def test_state_codes_and_current_quote_are_enforced(self):
        path,headers,data=self.configured()
        for region in ('California','ZZ'):
            self.assertEqual(self.client.post(path+'/quote',headers=headers,json={'contact':CONTACT|{'region':region}}).status_code,422)
        self.assertEqual(self.fake.count('/calculate'),0)
        self.assertEqual(self.client.post(path+'/payment',headers=headers,json={'quote_id':'not-reviewed'}).status_code,409)

    def test_price_drift_blocks_preparation_until_fresh_review(self):
        path,headers,data,q=self.quoted();self.fake.total='3.00'
        response=self.client.post(path+'/payment',headers=headers,json={'quote_id':q['quote_id']})
        self.assertEqual(response.status_code,409);self.assertEqual(self.fake.count('/authorize_payment'),0)
        q=self.client.post(path+'/quote',headers=headers,json={'contact':CONTACT,'shipping_id':2}).json()
        self.assertEqual(q['amount'],300)
        self.assertEqual(self.client.post(path+'/payment',headers=headers,json={'quote_id':q['quote_id']}).status_code,200)

    def test_repeated_preparation_and_resume_use_same_intent_without_reauthorizing(self):
        path,headers,data,payment=self.prepared();row=self.store.read(data['session_id'])
        again=self.client.post(path+'/payment',headers=headers,json={'quote_id':row['quote_id']})
        resumed=self.client.post(path+'/resume',headers=headers,json={})
        self.assertEqual(again.json()['client_secret'],payment['client_secret'])
        self.assertEqual(resumed.json()['client_secret'],payment['client_secret'])
        self.assertEqual(self.fake.count('/authorize_payment'),1)

    def test_lost_authorization_reply_is_held_then_resumes_same_prepared_intent(self):
        path,headers,data,q=self.quoted();self.transport.fail_after='/api/authorize'
        self.assertEqual(self.client.post(path+'/payment',headers=headers,json={'quote_id':q['quote_id']}).status_code,502)
        self.assertEqual(self.client.get(path,headers=headers).json()['status'],'needs_review')
        self.assertEqual(self.client.post(path+'/payment',headers=headers,json={'quote_id':q['quote_id']}).status_code,409)
        self.assertEqual(self.client.post(path+'/resume',headers=headers,json={}).status_code,200)
        self.assertEqual(self.fake.count('/authorize_payment'),1)

    def test_lost_capture_reply_returns_stored_receipt_without_another_capture(self):
        path,headers,data,payment=self.prepared();self.fake.confirmed.add(payment['payment_intent_id'])
        self.transport.fail_after='/api/capture';body={'payment_intent_id':payment['payment_intent_id']}
        self.assertEqual(self.client.post(path+'/complete',headers=headers,json=body).status_code,502)
        self.assertEqual(self.client.get(path,headers=headers).json()['status'],'captured')
        self.assertEqual(self.client.post(path+'/complete',headers=headers,json=body).json()['status'],'captured')
        self.assertEqual(self.fake.count('/new_order'),1)

    def test_uncertain_capture_does_not_retry_when_status_is_still_awaiting_card(self):
        path,headers,data,payment=self.prepared();self.fake.confirmed.add(payment['payment_intent_id'])
        self.transport.fail_before='/api/capture';body={'payment_intent_id':payment['payment_intent_id']}
        self.assertEqual(self.client.post(path+'/complete',headers=headers,json=body).status_code,502)
        self.assertEqual(self.client.get(path,headers=headers).json()['status'],'needs_review')
        self.assertEqual(self.client.post(path+'/complete',headers=headers,json=body).status_code,409)
        self.assertEqual(self.client.post(path+'/resume',headers=headers,json={}).status_code,409)
        self.assertEqual(self.fake.count('/new_order'),0)

    def test_no_tokens_contact_or_client_secrets_persist_in_api_database(self):
        path,headers,data,payment=self.prepared()
        raw=self.store.path.read_bytes()
        self.assertNotIn(data['session_token'].encode(),raw)
        self.assertNotIn(payment['client_secret'].encode(),raw)
        self.assertNotIn(CONTACT['email'].encode(),raw)
        self.assertNotIn(b'NEVER_EXPOSE_THIS',raw)
        self.assertEqual(self.store.path.stat().st_mode&0o777,0o600)

    def test_storage_restart_preserves_binding_and_holds_inflight_financial_operation(self):
        path,headers,data,q=self.quoted();before=self.store.read(data['session_id'])
        self.store.claim(data['session_id'],'authorize')
        restored=SessionStore(self.root/'sessions',clock=lambda:self.now)
        row=restored.authenticate(data['session_id'],'payment-test',data['session_token'])
        self.assertEqual(row['attempt'],before['attempt']);self.assertEqual(row['held'],'authorization_unknown')
        self.assertEqual(self.client.post(path+'/payment',headers=headers,json={'quote_id':q['quote_id']}).status_code,409)
        self.assertEqual(self.fake.count('/authorize_payment'),0)

    def test_origin_scope_and_site_specific_openapi_security(self):
        path,headers,data=self.create()
        self.assertEqual(self.client.get(path,headers=headers|{'Origin':'https://unregistered.example'}).status_code,403)
        spec=self.client.get('/sites/payment-test/openapi.json').json()
        session_path=BASE+'/{session_id}/payment'
        self.assertEqual(spec['paths'][session_path]['post']['security'],[{'CheckoutSession':[]}])
        self.assertEqual(spec['components']['schemas']['CreateSession']['properties'].keys(),{'plan_id'})
        self.assertNotIn('/api/authorize',str(spec['paths']))
        self.assertEqual(self.client.get(path.replace('/payment-test/','/other/'),headers=headers).status_code,404)

    def test_term_consent_is_required_for_subscription_and_one_time_prepaid(self):
        # The existing engine requires acceptance of the displayed terms for
        # native prepaid cycles even when the full plan does not auto-renew.
        path,headers,data,q=self.quoted()
        original=self.transport.call
        def reply(row,method,endpoint,body=None,client_ip=None):
            value,cookies=original(row,method,endpoint,body,client_ip)
            if endpoint=='/api/quote':
                value['option']=value['option']|{'recurring':True,'days':90,'prepaidCycles':4,'renewal':False,'renewalDays':None}
            return value,cookies
        self.transport.call=reply
        result=self.client.post(path+'/quote',headers=headers,json={'contact':CONTACT,'shipping_id':2})
        self.assertTrue(result.json()['terms_consent_required'])
        self.assertIn('No automatic renewal',result.json()['payment_terms'])
        self.fake.recurring=True
        link=self.engine.state.admin.get('link',self.link_id)
        link['options']=['706:54537:3'];self.engine.state.admin.put('link',self.link_id,link)
        self.store.update(data['session_id'],phase='new')
        # Standard subscription selection is server-owned as well.
        with self.store.db() as db:db.execute('UPDATE api_sessions SET selection=? WHERE id=?',('706:54537:3',data['session_id']))
        self.transport.call=original
        result=self.client.post(path+'/quote',headers=headers,json={'contact':CONTACT,'shipping_id':2})
        self.assertTrue(result.json()['terms_consent_required'])
        body={'quote_id':result.json()['quote_id'],'accept_terms':False}
        self.assertEqual(self.client.post(path+'/payment',headers=headers,json=body).status_code,422)
        self.assertEqual(self.fake.count('/authorize_payment'),0)
        body['accept_terms']=True
        self.assertEqual(self.client.post(path+'/payment',headers=headers,json=body).status_code,200)

    def test_public_key_changes_never_resume_a_payment_under_the_wrong_key(self):
        path,headers,data,payment=self.prepared()
        original=self.fake.detail
        def changed(endpoint):
            value=original(endpoint)
            if '/profiles/' in endpoint:value['fields']['account_fields']['publishable_key']='pk_test_changed'
            return value
        self.fake.detail=changed
        response=self.client.post(path+'/resume',headers=headers,json={})
        self.assertEqual(response.status_code,409)
        self.assertNotIn('client_secret',response.text)
        self.assertEqual(self.fake.count('/authorize_payment'),1)

    def test_configured_browser_origin_receives_cors_without_account_credentials(self):
        with patch.dict('os.environ',{'SITE_API_ALLOWED_ORIGINS':'https://shop.example'}):
            app=create_public_app(ORIGIN,read_catalog=lambda catalog:self.catalog,session_store=self.store,transport=self.transport)
        with TestClient(app,base_url=ORIGIN) as client:
            response=client.options(BASE,headers={'Origin':'https://shop.example','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'authorization,content-type'})
            self.assertEqual(response.headers.get('access-control-allow-origin'),'https://shop.example')
            created=client.post(BASE,headers={'Origin':'https://shop.example'},json={'plan_id':'sema-1m'})
            self.assertEqual(created.status_code,201)
            self.assertNotIn('access-control-allow-credentials',created.headers)

    def test_owner_allowed_any_origin_still_requires_the_correct_bearer_without_cookies(self):
        with patch.dict('os.environ',{'SITE_API_ALLOWED_ORIGINS':'*'}):
            app=create_public_app(ORIGIN,read_catalog=lambda catalog:self.catalog,session_store=self.store,transport=self.transport)
        with TestClient(app,base_url=ORIGIN) as client:
            origin='https://independent-frontend.example'
            preflight=client.options(BASE,headers={'Origin':origin,'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'authorization,content-type'})
            self.assertEqual(preflight.headers['access-control-allow-origin'],'*')
            self.assertNotIn('access-control-allow-credentials',preflight.headers)
            response=client.post(BASE,headers={'Origin':origin},json={'plan_id':'sema-1m'})
            self.assertEqual(response.status_code,201)
            data=response.json();path=BASE+'/'+data['session_id']
            self.assertEqual(client.get(path,headers={'Origin':origin}).status_code,401)
            authenticated=client.get(path,headers={'Origin':origin,'Authorization':'Bearer '+data['session_token']})
            self.assertEqual(authenticated.status_code,200)
            self.assertEqual(authenticated.headers['access-control-allow-origin'],'*')
            self.assertNotIn('access-control-allow-credentials',authenticated.headers)

class TransportTests(unittest.TestCase):
    def test_fixed_destination_paths_and_no_automatic_retry(self):
        with self.assertRaises(ValueError):CheckoutTransport('https://evil.example')
        transport=CheckoutTransport(PUBLIC_UPSTREAM)
        row={'cookies':'{}','csrf':'x','attempt':'attempt','link_id':'choice-'+'a'*32}
        with self.assertRaises(ValueError):transport.call(row,'POST','/api/v1/new_order',{})
        class Broken:
            count=0
            def request(self,method,path,body,headers):
                self.count+=1
                self.headers=dict(headers)
                raise OSError('unavailable')
            def close(self):pass
        broken=Broken()
        with patch('demo.session_api.http.client.HTTPSConnection',return_value=broken):
            with self.assertRaises(UpstreamError):transport.call(row,'POST','/api/authorize',{},'203.0.113.42')
        self.assertEqual(broken.count,1)
        self.assertEqual(broken.headers['Origin'],PUBLIC_UPSTREAM)
        self.assertNotIn('Fly-Client-IP',broken.headers)
        self.assertNotIn('Authorization',broken.headers)
