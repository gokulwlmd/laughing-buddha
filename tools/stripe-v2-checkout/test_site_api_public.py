import copy
import unittest
from fastapi.testclient import TestClient
from demo.public import create_public_app, map_catalog, PUBLISHED_PLAN, CATALOG_FRESH_SECONDS, CATALOG_MAX_AGE_SECONDS
from demo.publish import publication, DEMO_ID
from plans import choice_id


def fixture():
    entries=[]
    for treatment,prefix in [('Semaglutide','SEMA'),('Tirzepatide','TIRZ')]:
        for months in (1,3,6,12):
            for sub in (False,True):
                entries.append({'sku':f'{prefix}-{months}M'+('-SUB' if sub else ''),'available':True,
                    'durationMonths':months,'currency':'usd','treatmentId':prefix,'purchaseOptionId':f'plan-{months}',
                    # Real catalog semantics: days = gap between deliveries, renewalDays = days * cycles.
                    'options':[{'key':f'{len(entries)}:123:2','basePrice':'249.00','upfrontPrice':str(months*249),
                        'prepaidCycles':{1:1,3:1,6:2,12:4}[months], 'recurring':sub or months>=6,'renewal':sub,'days':90 if months>=6 else months*30,'renewalDays':months*30 if sub else None,'blockedReason':''}]})
    return {'id':PUBLISHED_PLAN,'paymentTestOnly':True,'treatments':[{'id':'SEMA','name':'Semaglutide'},{'id':'TIRZ','name':'Tirzepatide'}],
        'branding':{'color':'#245844'},'entries':entries}


class PublicDemoTests(unittest.TestCase):
    def setUp(self):
        self.now=1000;self.data=fixture();self.calls=0;self.catalogs=[]
        def read(catalog):
            self.calls+=1;self.catalogs.append(catalog)
            return self.data
        self.client=TestClient(create_public_app('https://demo.example',read,lambda:self.now),base_url='https://demo.example')
        self.base='/api/v1/sites/payment-test'

    def test_real_handoff_is_scoped_independent_and_expiring(self):
        catalog=self.client.get(self.base+'/plans').json()
        self.assertEqual(len(catalog['plans']),16)
        self.assertEqual(catalog['plans'][0]['price'],'249.00')
        links=[self.client.post(self.base+'/checkout',json={'plan_id':'sema-6m-sub'}).json()['checkout_url'] for _ in range(2)]
        self.assertNotEqual(*links)
        r=self.client.get(links[0],follow_redirects=False)
        self.assertEqual(r.status_code,303)
        self.assertIn('/c/'+choice_id(PUBLISHED_PLAN,'SEMA-6M-SUB','plan-6')+'?',r.headers['location'])
        self.assertIn('selection=',r.headers['location'])
        self.assertNotIn('/choose',r.headers['location'])
        self.assertNotIn('access=',r.headers['location'])
        self.now+=901
        self.assertEqual(self.client.get(links[1]).status_code,410)

    def test_rejects_price_routes_return_url_and_cross_origin(self):
        for key in ('price','amount','campaign_id','gateway_id','checkout_url','return_url'):
            self.assertEqual(self.client.post(self.base+'/checkout',json={'plan_id':'sema-1m',key:'bad'}).status_code,422)
        self.assertEqual(self.client.post(self.base+'/checkout',json={'plan_id':'bad'}).status_code,404)
        self.assertEqual(self.client.post(self.base+'/checkout',json={'plan_id':'sema-1m'},headers={'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.get('/api/v1/sites/other/plans').status_code,404)

    def test_scoped_docs_real_notice_and_no_payment_admin_routes(self):
        spec=self.client.get('/sites/payment-test/openapi.json').json()
        self.assertEqual(set(spec['paths']),{self.base,'/api/v1/domains/{domain}',self.base+'/plans',self.base+'/checkout',self.base+'/sessions',self.base+'/sessions/{session_id}',*[self.base+'/sessions/{session_id}/'+action for action in ('configuration','quote','payment','resume','complete','portal')]})
        self.assertIn('CheckoutSession',spec['components']['securitySchemes'])
        self.assertNotIn('return_url',str(spec))
        page=self.client.get('/').text
        self.assertIn('REAL CHARGES',page)
        self.assertIn('real Stripe v2',page)
        self.assertNotIn('NO PAYMENTS',page)
        self.assertNotIn('value="harbor-wellness"',page)
        for path in ('/api/authorize','/api/capture','/admin','/demo/checkout/foo/finish'):
            self.assertEqual(self.client.post(path,json={}).status_code,404)

    def test_cache_expires_and_upstream_errors_fail_closed(self):
        self.assertEqual(self.client.get(self.base+'/plans').status_code,200)
        self.assertEqual(self.client.get(self.base+'/plans').status_code,200)
        self.assertEqual(self.calls,1)
        self.data['paymentTestOnly']=False;self.now+=CATALOG_MAX_AGE_SECONDS+1
        self.assertEqual(self.client.get(self.base+'/plans').status_code,503)
        self.assertEqual(self.client.post(self.base+'/checkout',json={'plan_id':'sema-1m'}).status_code,503)

    def test_invalid_billing_data_fails_closed(self):
        for mutate in (lambda d:d['entries'][0].update(currency='usd$'),
            lambda d:d['entries'][0].update(durationMonths=0),
            lambda d:d['entries'][0]['options'][0].update(upfrontPrice='0',basePrice='0'),
            lambda d:d['entries'][0]['options'][0].update(upfrontPrice='abc'),
            lambda d:d['entries'][1]['options'][0].update(renewalDays=None),
            lambda d:d['entries'][4]['options'][0].update(days=0),
            lambda d:d['entries'][0].update(treatmentId='unknown'),
            lambda d:d.update(id='another-catalog'),
            lambda d:d.update(paymentTestOnly=False),
            lambda d:[e.update(available=False) for e in d['entries']]):
            data=fixture();mutate(data)
            with self.assertRaises(ValueError):map_catalog(data)

    def test_generic_mapping_follows_real_billing_rules(self):
        catalog,routes=map_catalog(fixture())
        plans={p.plan_id:p for p in catalog.plans}
        self.assertEqual(len(plans),16)
        self.assertEqual((plans['sema-1m'].purchase_type,plans['sema-1m'].renewal_days,plans['sema-1m'].shipment_days),('once',None,[0]))
        self.assertEqual((plans['sema-1m-sub'].purchase_type,plans['sema-1m-sub'].renewal_days),('subscription',30))
        # Prepaid: deliveries `days` apart, whole plan renews after renewalDays.
        self.assertEqual((plans['sema-6m'].purchase_type,plans['sema-6m'].shipment_days,plans['sema-6m'].price),('once',[0,90],'1494.00'))
        self.assertEqual((plans['sema-12m-sub'].renewal_days,plans['sema-12m-sub'].shipment_days),(360,[0,90,180,270]))
        self.assertIn('4 prepaid cycles, 90 days apart',plans['tirz-12m'].terms)
        # Other currencies and durations are no longer rejected.
        data=fixture();data['entries'][0]['currency']='cad';data['entries'][0]['durationMonths']=2
        p=next(x for x in map_catalog(data)[0].plans if x.plan_id=='sema-1m')
        self.assertEqual((p.currency,p.duration_months),('CAD',2));self.assertTrue(p.terms.startswith('Pay CA$249.00 upfront.'))
        # Blocked or unavailable entries are skipped, not fatal.
        data=fixture();data['entries'][0]['options'][0]['blockedReason']='x';data['entries'][1]['available']=False
        self.assertEqual(len(map_catalog(data)[0].plans),14)
        # A SKU listed under two purchase options keeps one plan.
        data=fixture();dup=copy.deepcopy(data['entries'][0]);dup['purchaseOptionId']='other';data['entries'].append(dup)
        self.assertEqual(len(map_catalog(data)[0].plans),16)
        # Several payment choices on one SKU get distinct, stable ids.
        data=fixture();extra=dict(data['entries'][0]['options'][0],key='999:123:3');data['entries'][0]['options'].append(extra)
        ids=[x.plan_id for x in map_catalog(data)[0].plans if x.plan_id.startswith('sema-1m-')]
        self.assertEqual(len([i for i in ids if i!='sema-1m-sub']),2)

    def test_publication_clones_children_preserves_source_and_stays_narrow(self):
        source={'id':'original-private','campaign_id':422,'therapy_id':'weight-loss','payment_test_only':True,
            'enabled':True,'visibility':'private','entries':[{'sku':str(i),'options':['1:2:3']} for i in range(16)]}
        children={choice_id(source['id'],str(i)):{'id':choice_id(source['id'],str(i)),'enabled':True,'visibility':'private','options':['1:2:3'],'plan_checkout_id':source['id']} for i in range(16)}
        class Admin:
            def records(self,kind):return [source,source|{'id':'site-api-demo-weight-loss','visibility':'public'}]
            def get(self,kind,key):return children.get(key)
        before=copy.deepcopy((source,children));records=publication(Admin())
        self.assertEqual((source,children),before)
        self.assertEqual(len(records),17)
        self.assertEqual(records[0][1]['id'],DEMO_ID)
        self.assertEqual(records[0][1]['visibility'],'public')
        self.assertTrue(all(c['visibility']=='public' and c['plan_checkout_id']==DEMO_ID for _,c in records[1:]))
        self.assertFalse(set(c['id'] for _,c in records[1:]) & set(children))

    def test_publication_is_atomic_idempotent_and_never_overwrites(self):
        import sqlite3
        import tempfile
        from pathlib import Path
        from demo.publish import publish
        source={'id':'original-private','campaign_id':422,'therapy_id':'weight-loss','payment_test_only':True,
            'enabled':True,'visibility':'private','entries':[{'sku':str(i),'options':['1:2:3']} for i in range(16)]}
        children={choice_id(source['id'],str(i)):{'id':choice_id(source['id'],str(i)),'enabled':True,'visibility':'private','options':['1:2:3'],'plan_checkout_id':source['id']} for i in range(16)}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'db'
            class Store:
                def db(self):return sqlite3.connect(path)
            class Admin:
                store=Store()
                def records(self,kind):return [source,source|{'id':'site-api-demo-weight-loss','visibility':'public'}]
                def get(self,kind,key):return children.get(key)
                def plan_record(self,key):return source,{},{}
                def plan_options(self,*args):return {'entries':[{'available':True} for _ in range(16)]}
            a=Admin()
            with a.store.db() as db:
                db.execute('CREATE TABLE admin_config(kind TEXT,id TEXT,data TEXT,PRIMARY KEY(kind,id))')
                db.execute("INSERT INTO admin_config VALUES('untouched','original','keep me')")
            self.assertEqual(publish(a)['published_records'],17)
            self.assertEqual(publish(a)['published_records'],0)
            with a.store.db() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM admin_config').fetchone()[0],18)
                self.assertEqual(db.execute("SELECT data FROM admin_config WHERE kind='untouched'").fetchone()[0],'keep me')
                self.assertEqual(db.execute('SELECT COUNT(*) FROM public_demo_publications').fetchone()[0],1)
                db.execute("UPDATE admin_config SET data='{}' WHERE kind='plan_checkout'")
            with self.assertRaises(RuntimeError):publish(a)
            with a.store.db() as db:
                self.assertEqual(db.execute("SELECT data FROM admin_config WHERE kind='plan_checkout'").fetchone()[0],'{}')


    def test_refresh_keeps_a_valid_display_catalog_responsive_and_expires_stale_data(self):
        import threading
        started=threading.Event();release=threading.Event();finished=threading.Event()
        calls=[]
        def read(catalog):
            calls.append(1)
            if len(calls)>1:
                started.set();release.wait(3);finished.set()
                raise ValueError('upstream unavailable')
            return fixture()
        client=TestClient(create_public_app('https://demo.example',read,lambda:self.now),base_url='https://demo.example')
        try:
            self.assertEqual(client.get(self.base+'/plans').status_code,200)
            self.now+=CATALOG_FRESH_SECONDS+1
            # The second request returns while the background read remains blocked.
            self.assertEqual(client.get(self.base+'/plans').status_code,200)
            self.assertTrue(started.wait(1))
            self.assertFalse(finished.is_set())
            self.assertEqual(client.get(self.base+'/plans').status_code,200)
            self.assertEqual(len(calls),2)
        finally:
            release.set();finished.wait(1);client.close()
