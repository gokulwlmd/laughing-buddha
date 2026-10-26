"""Site publication, selection and checkout isolation. No network/provider writes."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from fastapi.testclient import TestClient
from app import Settings, create_app
from demo.public import create_public_app, map_site_catalog, PUBLISHED_PLAN
from demo.registry import load_publications
from demo.publish import site_publication, publish_site
from demo.session_api import PUBLIC_UPSTREAM, SessionStore
from plans import choice_id
from test_site_api_public import fixture
from test_site_session_api import PaymentFake, EngineTransport
from test_checkout import CONTACT


def configured_site():
    site = {'site_id':'fortifyhp','site_name':'FortifyHP','brand_id':'fortify-brand','campaign_id':195,
        'portal_site_id':'fortifyhp','color':'#A2563F','therapies':[]}
    catalogs = {}
    for therapy,name,prefix in [('weight-loss','Weight Loss','SEMA'),('sermorelin','Sermorelin','SERM'),
                                ('metformin','Metformin','METFORM'),('pt-141','PT-141','PT141')]:
        publication = 'site-api-fortifyhp-'+therapy
        data = copy.deepcopy(fixture())
        data.update(id=publication,paymentTestOnly=False,treatments=[{'id':prefix,'name':name}])
        data['entries'] = data['entries'][:8]
        approved = []
        for index,entry in enumerate(data['entries']):
            entry['sku'] = entry['sku'].replace('SEMA',prefix)
            entry['treatmentId'] = prefix
            option = entry['options'][0]
            option['key'] = f'{706+index}:54537:{3 if index%2 else 2}'
            if entry['durationMonths'] >= 6:
                option['days'] = 90
            approved.append({'sku':entry['sku'],'selection':option['key'],'purchase_option_id':entry['purchaseOptionId']})
        site['therapies'].append({'therapy_id':therapy,'name':name,'source_plan_id':'source-'+therapy,
            'published_plan_id':publication,'plans':approved})
        catalogs[publication] = data
    return {'version':1,'sites':[site]},catalogs


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.manifest,self.catalogs = configured_site()
        self.reads=[]
        def read(key):
            self.reads.append(key)
            return self.catalogs[key]
        self.client=TestClient(create_public_app('https://api.example',read_catalog=fixture,
            manifest=self.manifest,read_publication=read),base_url='https://api.example')

    def tearDown(self):
        self.client.close()

    def test_client_four_therapies_and_filter_use_only_explicit_mappings(self):
        response=self.client.get('/api/v1/sites/fortifyhp/plans')
        self.assertEqual(response.status_code,200,response.text)
        data=response.json()
        self.assertEqual(data['site_name'],'FortifyHP')
        self.assertFalse(data['demo']);self.assertFalse(data['payment_test_only'])
        self.assertEqual(len(data['plans']),32)
        self.assertEqual({t['therapy_id'] for t in data['therapies']},{'weight-loss','sermorelin','metformin','pt-141'})
        twelve=next(p for p in data['plans'] if p['plan_id']=='sema-12m-sub')
        self.assertEqual(twelve['shipment_days'],[0,90,180,270])
        self.assertEqual(twelve['renewal_days'],360)
        self.assertEqual(twelve['price'],'2988.00')
        filtered=self.client.get('/api/v1/sites/fortifyhp/plans?therapy_id=metformin').json()
        self.assertEqual(len(filtered['plans']),8)
        self.assertTrue(all(p['therapy_id']=='metformin' for p in filtered['plans']))
        self.assertEqual(self.client.get('/api/v1/sites/fortifyhp/plans?therapy_id=not-approved').status_code,404)
        self.assertEqual(len(self.reads),4)
        self.assertEqual(self.client.get('/api/v1/sites/fortifyhp/therapies').json(),data['therapies'])
        self.assertEqual(len(self.client.get('/api/v1/sites/payment-test/plans').json()['plans']),16)

    def test_scoped_swagger_and_redirect_never_point_at_payment_test(self):
        spec=self.client.get('/sites/fortifyhp/openapi.json').json()
        self.assertIn('FortifyHP',spec['info']['title'])
        self.assertNotIn('no medication',spec['info']['description'])
        self.assertTrue(all(path.startswith('/api/v1/sites/fortifyhp/') for path in spec['paths']))
        response=self.client.post('/api/v1/sites/fortifyhp/checkout',json={'plan_id':'sema-1m'})
        redirect=self.client.get(response.json()['checkout_url'],follow_redirects=False)
        expected=choice_id('site-api-fortifyhp-weight-loss','SEMA-1M','plan-1')
        self.assertIn('/c/'+expected+'?',redirect.headers['location'])
        self.assertNotIn(choice_id(PUBLISHED_PLAN,'SEMA-1M','plan-1'),redirect.headers['location'])
        self.assertEqual(self.client.get('/sites/missing/openapi.json').status_code,404)
        self.assertEqual(self.client.get('/api/v1/sites/missing/plans').status_code,404)

    def test_client_catalog_drift_fails_closed_and_unlisted_entries_are_not_sold(self):
        site=load_publications(self.manifest)['fortifyhp']
        for mutate in (lambda d:d.update(paymentTestOnly=True),lambda d:d.update(id=PUBLISHED_PLAN),
                lambda d:d['entries'][0].update(available=False),
                lambda d:d['entries'][0]['options'][0].update(key='999:999:2'),
                lambda d:d['entries'][4]['options'][0].update(days=180),
                lambda d:d['entries'][7]['options'][0].update(renewalDays=365)):
            values=copy.deepcopy(self.catalogs);mutate(values[site.therapies[0].published_plan_id])
            with self.assertRaises(ValueError):map_site_catalog(site,values.__getitem__)
        values=copy.deepcopy(self.catalogs)
        values[site.therapies[0].published_plan_id]['entries'].append({'sku':'UNAPPROVED','available':True})
        self.assertEqual(len(map_site_catalog(site,values.__getitem__)[0].plans),32)

    def test_invalid_manifest_cannot_override_test_site_or_share_portals_or_routes(self):
        for mutate in (lambda m:m['sites'][0].update(site_id='payment-test'),
                lambda m:m['sites'][0]['therapies'][0].update(published_plan_id='../private'),
                lambda m:m['sites'][0]['therapies'][0]['plans'][0].update(selection='url:https://evil.example'),
                lambda m:m['sites'][0]['therapies'][1]['plans'][0].update(sku='SEMA-1M'),
                lambda m:m['sites'].append(copy.deepcopy(m['sites'][0])|{'site_id':'another'})):
            value=copy.deepcopy(self.manifest);mutate(value)
            with self.assertRaises(ValueError):load_publications(value)


class SiteSessionIsolationTests(unittest.TestCase):
    def test_same_sku_two_sites_has_separate_attempts_and_rejects_cross_site_tokens(self):
        manifest,catalogs=configured_site()
        with tempfile.TemporaryDirectory() as directory:
            fake=PaymentFake()
            engine=create_app(Settings(public_url=PUBLIC_UPSTREAM,state_dir=Path(directory)/'upstream',authorization_verified=True),fake)
            for brand,campaign,parent,test_only in [('test-brand',422,PUBLISHED_PLAN,True),('fortify-brand',195,'site-api-fortifyhp-weight-loss',False)]:
                engine.state.admin.put('brand',brand,{'id':brand,'name':brand,'campaign_id':campaign,'color':'#A2563F'})
                key=choice_id(parent,'SEMA-1M','plan-1')
                engine.state.admin.put('link',key,{'id':key,'brand_id':brand,'campaign_id':campaign,'sku':'SEMA-1M',
                    'options':['706:54537:2'],'visibility':'public','enabled':True,'revision':1,'title':brand,'payment_test_only':test_only})
            legacy=fixture();legacy['entries'][0]['options'][0]['key']='706:54537:2'
            store=SessionStore(Path(directory)/'sessions')
            transport=EngineTransport(engine)
            with TestClient(create_public_app('https://api.example',read_catalog=lambda:legacy,manifest=manifest,
                    read_publication=catalogs.__getitem__,session_store=store,transport=transport),base_url='https://api.example') as client:
                paths=[];credentials=[];rows=[]
                for site in ('payment-test','fortifyhp'):
                    base='/api/v1/sites/'+site+'/sessions'
                    created=client.post(base,json={'plan_id':'sema-1m'})
                    self.assertEqual(created.status_code,201,created.text)
                    data=created.json();headers={'Authorization':'Bearer '+data['session_token']}
                    path=base+'/'+data['session_id'];paths.append(path);credentials.append(headers)
                    rows.append(store.read(data['session_id']))
                    cfg=client.get(path+'/configuration',headers=headers)
                    self.assertEqual(cfg.status_code,200,cfg.text)
                    self.assertEqual(cfg.json()['payment_test_only'],site=='payment-test')
                    quote=client.post(path+'/quote',headers=headers,json={'contact':CONTACT,'shipping_id':2})
                    self.assertEqual(quote.status_code,200,quote.text)
                self.assertNotEqual(rows[0]['link_id'],rows[1]['link_id'])
                self.assertNotEqual(rows[0]['attempt'],rows[1]['attempt'])
                for path,headers in zip(paths,credentials):
                    other=path.replace('/payment-test/','/fortifyhp/') if '/payment-test/' in path else path.replace('/fortifyhp/','/payment-test/')
                    self.assertEqual(client.get(other,headers=headers).status_code,401)
                self.assertEqual(client.get(paths[0],headers=credentials[1]).status_code,401)
                calculate=[body for _,path,body in fake.calls if path.endswith('/calculate')]
                self.assertEqual({body['campaign_id'] for body in calculate},{195,422})
                self.assertEqual(fake.count('/authorize_payment'),0)
                self.assertEqual(fake.count('/new_order'),0)
                # Complete only a fake Fortify order and verify its handoff can
                # never return an account on another site's patient portal.
                prepared=client.post(paths[1]+'/payment',headers=credentials[1],json={'quote_id':quote.json()['quote_id']})
                self.assertEqual(prepared.status_code,200,prepared.text)
                fake.confirmed.add(prepared.json()['payment_intent_id'])
                completed=client.post(paths[1]+'/complete',headers=credentials[1],json={'payment_intent_id':prepared.json()['payment_intent_id']})
                self.assertEqual(completed.status_code,200,completed.text)
                self.assertEqual(completed.json()['status'],'captured')
                engine.state.member_portal.receipt_invite=lambda row:{'site_id':'other-site',
                    'enrollment_url':PUBLIC_UPSTREAM+'/portal/other-site#invite=synthetic','expires_at':None}
                self.assertEqual(client.post(paths[1]+'/portal',headers=credentials[1],json={}).status_code,502)
                engine.state.member_portal.receipt_invite=lambda row:{'site_id':'fortifyhp',
                    'enrollment_url':PUBLIC_UPSTREAM+'/portal/fortifyhp#invite=synthetic','expires_at':None}
                self.assertEqual(client.post(paths[1]+'/portal',headers=credentials[1],json={}).status_code,200)
                self.assertEqual(fake.count('/new_order'),1)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.manifest,self.catalogs=configured_site();self.site=self.manifest['sites'][0]
        self.temp=tempfile.TemporaryDirectory();path=Path(self.temp.name)/'store.sqlite3'
        sources={};links={};catalogs=self.catalogs
        for therapy in self.site['therapies']:
            sources[therapy['source_plan_id']]={'id':therapy['source_plan_id'],'campaign_id':195,'brand_id':'fortify-brand',
                'therapy_id':therapy['therapy_id'],'enabled':True,'visibility':'private','payment_test_only':False,
                'entries':[{'sku':p['sku'],'purchase_option_id':p['purchase_option_id'],'options':[p['selection']]} for p in therapy['plans']]}
            for p in therapy['plans']:
                key=choice_id(therapy['source_plan_id'],p['sku'],p['purchase_option_id'])
                links[key]={'id':key,'campaign_id':195,'brand_id':'fortify-brand','plan_checkout_id':therapy['source_plan_id'],
                    'sku':p['sku'],'options':[p['selection']],'enabled':True,'visibility':'private'}
        class Store:
            def db(self):return sqlite3.connect(path)
        class Admin:
            store=Store()
            def plan_record(self,key):return sources[key],{'id':'fortify-brand'},{}
            def plan_options(self,source,*args):return catalogs['site-api-fortifyhp-'+source['therapy_id']]
            def get(self,kind,key):return links.get(key)
        self.admin=Admin();self.sources=sources;self.links=links
        with self.admin.store.db() as db:
            db.execute('CREATE TABLE admin_config(kind TEXT,id TEXT,data TEXT,PRIMARY KEY(kind,id))')
            db.execute("INSERT INTO admin_config VALUES('untouched','original','keep me')")

    def tearDown(self):self.temp.cleanup()

    def test_publication_is_atomic_idempotent_preserves_sources_and_never_overwrites(self):
        before=copy.deepcopy((self.sources,self.links))
        records=site_publication(self.admin,self.site)
        self.assertEqual(len(records),36)
        self.assertEqual((self.sources,self.links),before)
        self.assertTrue(all(record['visibility']=='public' for _,record in records))
        self.assertTrue(all(record['campaign_id']==195 for _,record in records))
        self.assertEqual(publish_site(self.admin,self.site)['published_records'],36)
        self.assertEqual(publish_site(self.admin,self.site)['published_records'],0)
        with self.admin.store.db() as db:
            self.assertEqual(db.execute("SELECT data FROM admin_config WHERE kind='untouched'").fetchone()[0],'keep me')
            db.execute("UPDATE admin_config SET data='{}' WHERE kind='plan_checkout'")
        with self.assertRaises(RuntimeError):publish_site(self.admin,self.site)

    def test_cross_campaign_test_only_or_changed_selection_cannot_publish(self):
        source=self.sources['source-weight-loss']
        for field,value in [('campaign_id',422),('brand_id','other-brand'),('payment_test_only',True)]:
            before=source.get(field);source[field]=value
            with self.assertRaises(RuntimeError):publish_site(self.admin,self.site)
            source[field]=before
        self.catalogs['site-api-fortifyhp-pt-141']['entries'][0]['options'][0]['key']='1:2:3'
        with self.assertRaises(RuntimeError):publish_site(self.admin,self.site)
        with self.admin.store.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM admin_config').fetchone()[0],1)
