"""Shared runtime keeps original routes/payments and reloads site publications."""
import copy
from http.cookies import SimpleCookie
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app import create_app, Settings
from demo.runtime import install_site_api, ManifestFile
from demo.session_api import UpstreamError, PUBLIC_UPSTREAM
from plans import choice_id
from test_site_session_api import PaymentFake
from test_site_api_registry import configured_site
from test_checkout import CONTACT


class LocalTransport:
    upstream=PUBLIC_UPSTREAM
    def __init__(self,engine):self.engine=engine
    def call(self,row,method,path,body=None,client_ip=None):
        cookies=json.loads(row['cookies'])
        headers={'Origin':self.upstream,'Cookie':'; '.join(k+'='+v for k,v in cookies.items()),'X-CSRF-Token':row['csrf']}
        if row['attempt']:headers['X-Checkout-Attempt']=row['attempt']
        with TestClient(self.engine,base_url=self.upstream) as client:
            response=client.request(method,path,params={'link_id':row['link_id']} if path.startswith('/api/') else None,
                headers=headers,json=body)
        if response.status_code>=400:raise UpstreamError(response.status_code,response.json().get('detail','Rejected'))
        for value in response.headers.get_list('set-cookie'):
            parsed=SimpleCookie();parsed.load(value);cookies.update({k:v.value for k,v in parsed.items()})
        return (response.text if path.startswith('/c/') else response.json()),cookies


class SharedSiteAPITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)
        self.fake=PaymentFake()
        self.engine=create_app(Settings(public_url=PUBLIC_UPSTREAM,state_dir=self.path,authorization_verified=True),self.fake)
        self.manifest_path=self.path/'site-api-publications.json'
    def tearDown(self):self.temp.cleanup()

    def fixtures(self):
        manifest,catalogs=configured_site();site=manifest['sites'][0];admin=self.engine.state.admin
        admin.put('brand','fortify-brand',{'id':'fortify-brand','name':'FortifyHP','campaign_id':195,'color':'#A2563F'})
        admin.put('site','fortifyhp',{'id':'fortifyhp','name':'FortifyHP','campaign_id':195,'brand_id':'fortify-brand'})
        public_id='site-api-fortifyhp-weight-loss'
        key=choice_id(public_id,'SEMA-1M','plan-1')
        admin.put('link',key,{'id':key,'brand_id':'fortify-brand','campaign_id':195,'sku':'SEMA-1M',
            'options':['706:54537:2'],'visibility':'public','enabled':True,'revision':1,'title':'FortifyHP','payment_test_only':False})
        reads=[]
        def record(key):
            reads.append(key)
            therapy=next(t for t in site['therapies'] if t['published_plan_id']==key)
            return {'id':key,'site_id':'fortifyhp','brand_id':'fortify-brand','campaign_id':195,
                'visibility':'public','therapy_id':therapy['therapy_id']},{},{}
        admin.plan_record=record
        admin.plan_options=lambda plan,*args:copy.deepcopy(catalogs[plan['id']])
        return manifest,catalogs,reads

    def install(self):
        return install_site_api(self.engine,self.manifest_path,LocalTransport(self.engine))

    def test_missing_manifest_keeps_original_routes_config_and_payment_state(self):
        self.engine.state.store.create(422,'EXISTING-SKU')
        before=self.engine.state.settings.__dict__.copy()
        with self.engine.state.store.db() as db:rows=db.execute('SELECT * FROM checkouts').fetchall()
        self.install()
        with TestClient(self.engine,base_url=PUBLIC_UPSTREAM) as client:
            self.assertEqual(client.get('/health').status_code,200)
            self.assertEqual(client.get('/admin').status_code,200)
            root=client.get('/',follow_redirects=False)
            self.assertIn('/checkout/422/',root.headers['location'])
            self.assertEqual(client.get('/api/v1/sites/fortifyhp/plans').status_code,404)
            self.assertEqual(client.get('/api/v1/sites/payment-test/plans').status_code,404)
            self.assertEqual(client.get('/sites/payment-test/docs').status_code,404)
            self.assertEqual(client.get('/api/config?campaign_id=422').status_code,401)
            self.assertEqual(client.get('/api/v1/sites/missing/portal/config').status_code,404)
        self.assertEqual(self.engine.state.settings.__dict__,before)
        with self.engine.state.store.db() as db:self.assertEqual(db.execute('SELECT * FROM checkouts').fetchall(),rows)
        self.assertEqual(self.fake.calls,[])

    def test_valid_manifest_hot_reloads_without_payment_restart_and_invalid_replacement_fails_closed(self):
        manifest,catalogs,reads=self.fixtures();facade=self.install()
        with TestClient(self.engine,base_url=PUBLIC_UPSTREAM) as client:
            self.assertEqual(client.get('/api/v1/sites/fortifyhp/plans').status_code,404)
            self.manifest_path.write_text(json.dumps(manifest))
            response=client.get('/api/v1/sites/fortifyhp/plans')
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(set(reads),set(catalogs))
            self.manifest_path.write_text('{broken')
            self.assertEqual(client.get('/api/v1/sites/fortifyhp/plans').status_code,503)
            self.assertEqual(client.get('/health').status_code,200)
            self.assertEqual(set(facade.state.publications),{'fortifyhp'})
            self.manifest_path.write_text(json.dumps(manifest))
            self.assertEqual(client.get('/api/v1/sites/fortifyhp/plans').status_code,200)
            spec=client.get('/sites/fortifyhp/openapi.json')
            self.assertEqual(spec.status_code,200,spec.text)
            self.assertNotIn('/api/v1/sites/fortifyhp/checkout',spec.json()['paths'])
            self.assertIn('/api/v1/sites/fortifyhp/sessions',spec.json()['paths'])
            self.assertEqual(client.get('/sites/fortifyhp/docs').status_code,200)

    def test_same_origin_payment_and_portal_routes_preserve_separate_auth(self):
        manifest,_,_=self.fixtures();self.manifest_path.write_text(json.dumps(manifest))
        with patch.dict('os.environ',{'SITE_API_ALLOWED_ORIGINS':'*'}):self.install()
        with TestClient(self.engine,base_url=PUBLIC_UPSTREAM) as client:
            # Portal route wins before the API mount and still serves its real
            # site model; it does not inherit permissive API CORS/auth handling.
            portal=client.get('/api/v1/sites/fortifyhp/portal/configuration')
            self.assertEqual(portal.status_code,200,portal.text)
            self.assertEqual(portal.json()['site']['theme'],'fortifyhp')
            self.assertEqual(client.get('/api/v1/sites/fortifyhp/portal/me').status_code,401)
            created=client.post('/api/v1/sites/fortifyhp/sessions',headers={'Origin':'https://frontend.example'},json={'plan_id':'sema-1m'})
            self.assertEqual(created.status_code,201,created.text)
            self.assertEqual(created.headers.get('access-control-allow-origin'),'*')
            session=created.json();base='/api/v1/sites/fortifyhp/sessions/'+session['session_id']
            headers={'Authorization':'Bearer '+session['session_token']}
            self.assertEqual(client.get(base+'/configuration',headers=headers).status_code,200)
            quote=client.post(base+'/quote',headers=headers,json={'contact':CONTACT,'shipping_id':2})
            self.assertEqual(quote.status_code,200,quote.text)
            payment=client.post(base+'/payment',headers=headers,json={'quote_id':quote.json()['quote_id']})
            self.assertEqual(payment.status_code,200,payment.text)
            self.fake.confirmed.add(payment.json()['payment_intent_id'])
            complete=client.post(base+'/complete',headers=headers,json={'payment_intent_id':payment.json()['payment_intent_id']})
            self.assertEqual(complete.status_code,200,complete.text)
            self.assertEqual(complete.json()['status'],'captured')
            self.engine.state.member_portal.receipt_invite=lambda row:{'site_id':'fortifyhp',
                'enrollment_url':PUBLIC_UPSTREAM+'/portal/fortifyhp#invite=synthetic','expires_at':None}
            enrollment=client.post(base+'/portal',headers=headers,json={})
            self.assertEqual(enrollment.status_code,200,enrollment.text)
            self.assertEqual(self.fake.count('/new_order'),1)

    def test_opt_in_and_file_signature_cache(self):
        with patch.dict('os.environ',{},clear=True):self.assertIsNone(install_site_api(self.engine))
        loader=ManifestFile(self.manifest_path)
        empty=loader();self.assertIs(loader(),empty)
        self.manifest_path.write_text('{"version":1,"sites":[]}')
        self.assertIsNot(loader(),empty)
        cached=loader();self.assertIs(loader(),cached)
