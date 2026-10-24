"""Publication/export uses verified local objects; no provider writes or patients."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from app import Settings, create_app
from fortifyhp_publish_api import build_configuration, export_manifest, ORIGIN
from plans import choice_id
from sites import checkout_id
from therapy_skeletons import all_skeletons
from test_site_session_api import PaymentFake


class FortifyPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)
        self.fake=PaymentFake()
        self.app=create_app(Settings(public_url=ORIGIN,state_dir=self.path,authorization_verified=True),self.fake)
        admin=self.app.state.admin;self.admin=admin;self.catalogs={}
        brand={'id':'fortifyhp','name':'FortifyHP','campaign_id':195,'color':'#A2563F'}
        admin.put('brand','fortifyhp',brand)
        admin.put('site','fortifyhp',{'id':'fortifyhp','name':'FortifyHP','brand_id':'fortifyhp','campaign_id':195})
        self.ids=[]
        for skeleton in all_skeletons():
            therapy=skeleton['therapy'];tid=therapy['id']
            key=checkout_id('fortifyhp','fortifyhp-'+tid);self.ids.append(key)
            source={'id':key,'site_id':'fortifyhp','brand_id':'fortifyhp','campaign_id':195,'therapy_id':tid,
                'enabled':True,'visibility':'private','payment_test_only':False,'entries':[]}
            catalog={'id':key,'paymentTestOnly':False,'treatments':therapy['treatments'],'entries':[]}
            for index,product in enumerate(skeleton['products']):
                sku=product['sku'];months=product['duration_months'];count={1:1,3:1,6:2,12:4}[months]
                renewal=sku.endswith('-SUB');purchase='fortifyhp-'+tid+'-'+str(months)+'m'
                selection=f'{700+index}:54537:{3 if renewal else 2}'
                source['entries'].append({'sku':sku,'options':[selection],'purchase_option_id':purchase})
                catalog['entries'].append({'sku':sku,'purchaseOptionId':purchase,'available':True,'durationMonths':months,
                    'currency':'USD','treatmentId':product['treatment_id'],'options':[{'key':selection,'basePrice':'49.00',
                    'upfrontPrice':str(49*months),'prepaidCycles':count,'recurring':renewal or count>1,
                    'renewal':renewal,'days':90 if count>1 else months*30,'renewalDays':months*30 if renewal else None}]})
                admin.put('master',sku,{'sku':sku,'therapy_id':tid,'enabled':True})
                child=choice_id(key,sku,purchase)
                admin.put('link',child,{'id':child,'brand_id':'fortifyhp','campaign_id':195,'plan_checkout_id':key,
                    'sku':sku,'enabled':True,'options':[selection],'visibility':'private'})
            admin.put('plan_checkout',key,source);admin.put('therapy',tid,therapy)
            self.catalogs[key]=catalog
        admin.plan_record=lambda key:(admin.get('plan_checkout',key),brand,{})
        admin.plan_options=lambda source,*args:copy.deepcopy(self.catalogs[source['id']])

    def tearDown(self):self.temp.cleanup()

    def test_exports_exact_forty_plans_and_branded_portal_atomically_and_idempotently(self):
        configured=build_configuration(self.admin,self.ids)
        self.assertEqual(sum(len(t.plans) for t in configured.therapies),40)
        first=export_manifest(self.app,source_plan_ids=self.ids)
        self.assertEqual(first['plans'],40);self.assertEqual(first['published_records'],44)
        self.assertEqual(first['portal_theme'],'fortifyhp')
        target=self.path/'site-api-publications.json'
        saved=target.read_bytes()
        self.assertEqual(target.stat().st_mode&0o777,0o600)
        self.assertEqual(json.loads(saved)['sites'][0]['campaign_id'],195)
        self.assertEqual(export_manifest(self.app,source_plan_ids=self.ids)['published_records'],0)
        self.assertEqual(target.read_bytes(),saved)
        self.assertEqual(self.fake.calls,[])
        with self.admin.store.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM member_patients').fetchone()[0],0)

    def test_unverified_missing_plan_wrong_portal_or_existing_manifest_prevents_export(self):
        source=self.admin.get('plan_checkout',self.ids[0]);saved=copy.deepcopy(source)
        source['entries'].pop();self.admin.put('plan_checkout',source['id'],source)
        with self.assertRaises(ValueError):export_manifest(self.app)
        self.admin.put('plan_checkout',saved['id'],saved)
        site=self.admin.get('site','fortifyhp');site['portal_theme']='default';self.admin.put('site','fortifyhp',site)
        with self.assertRaises(ValueError):export_manifest(self.app)
        site['portal_theme']='fortifyhp';self.admin.put('site','fortifyhp',site)
        target=self.path/'site-api-publications.json'
        other=build_configuration(self.admin).model_dump(mode='json');other['site_name']='Changed site'
        text=json.dumps({'sites':[other]});target.write_text(text)
        with self.assertRaises(ValueError):export_manifest(self.app)
        self.assertEqual(target.read_text(),text)
        self.assertFalse(any(p['id'].startswith('site-api-') for p in self.admin.records('plan_checkout')))

    def test_unavailable_source_payment_selection_never_produces_manifest_or_partial_publication(self):
        self.catalogs[self.ids[-1]]['entries'][0]['available']=False
        with self.assertRaises(RuntimeError):export_manifest(self.app)
        self.assertFalse((self.path/'site-api-publications.json').exists())
        self.assertFalse(any(p['id'].startswith('site-api-') for p in self.admin.records('plan_checkout')))
        with self.assertRaises(ValueError):build_configuration(self.admin,self.ids[:3])

    def test_export_preserves_other_client_manifest_entries(self):
        other=build_configuration(self.admin).model_dump(mode='json')
        other.update(site_id='another-client',site_name='Another client',brand_id='another-brand',campaign_id=777,portal_site_id='another-portal')
        for therapy in other['therapies']:
            therapy['published_plan_id']='another-'+therapy['therapy_id']
        target=self.path/'site-api-publications.json'
        target.write_text(json.dumps({'version':1,'sites':[other]}))
        export_manifest(self.app)
        saved=json.loads(target.read_text())
        self.assertEqual(saved['sites'][0],other)
        self.assertEqual(saved['sites'][1]['site_id'],'fortifyhp')
