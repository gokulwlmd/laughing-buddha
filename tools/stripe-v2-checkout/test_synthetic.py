"""A staging flag cannot be used to authorize real catalog or payment calls."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import Settings, Sticky, create_app
from synthetic import SyntheticSticky


class SyntheticTests(unittest.TestCase):
    def test_staging_ignores_credentials_and_forces_payment_block_even_if_enabled(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(Sticky,'call',side_effect=AssertionError('No network allowed')):
            app=create_app(Settings(public_url='https://demo.example',state_dir=Path(directory),synthetic=True,authorization_verified=True))
            client=TestClient(app,base_url='https://demo.example')
            health=client.get('/health').json();self.assertTrue(health['payments_blocked']);self.assertTrue(health['synthetic'])
            self.assertFalse(app.state.settings.authorization_verified);self.assertIsNone(app.state.admin.owner())
            admin=app.state.admin;client.get('/?access='+app.state.invite)
            headers={'Origin':'https://demo.example','X-CSRF-Token':app.state.invite}
            # The payment gate is exercised with valid origin/access/CSRF below.
            import hashlib,hmac
            headers['X-CSRF-Token']=hmac.new(app.state.invite.encode(),b'checkout-csrf',hashlib.sha256).hexdigest()
            for endpoint,body in [('authorize',{'quote_id':'anything'}),('capture',{}),('payment-state',{})]:
                if endpoint=='payment-state':continue
                self.assertEqual(client.post('/api/'+endpoint,headers=headers,json=body).status_code,503)
            self.assertEqual(len(admin.records('master')),8)
            admin.put('brand','demo-brand',admin.get('brand','demo-brand')|{'name':'Saved demo design'})
            restarted=create_app(Settings(public_url='https://demo.example',state_dir=Path(directory),synthetic=True))
            self.assertEqual(restarted.state.admin.get('brand','demo-brand')['name'],'Saved demo design')
            self.assertEqual(len(restarted.state.admin.records('master')),8)

    def test_synthetic_catalog_persists_and_rejects_payment_operations(self):
        with tempfile.TemporaryDirectory() as directory:
            api=SyntheticSticky(directory)
            for path in ('/api/v1/authorize_payment','/api/v1/new_order'):
                with self.assertRaises(RuntimeError):api.call('POST',path,{})
            created=api.call('POST','/api/v2/products',{'sku':'DEMO','price':'10.00','is_taxable':0})['data']['id']
            self.assertEqual(SyntheticSticky(directory).detail('/api/v2/products/'+str(created))['sku'],'DEMO')

    def test_environment_forces_staging_payment_block(self):
        with patch.dict(os.environ,{'CHECKOUT_ENVIRONMENT':'staging','CHECKOUT_AUTHORIZATION_VERIFIED':'1','CHECKOUT_PUBLIC_URL':'https://staging.example'}):
            settings=Settings.environment();self.assertTrue(settings.synthetic);self.assertFalse(settings.authorization_verified)


class StarterCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.app=create_app(Settings(public_url='http://localhost:8081',state_dir=Path(self.temp.name),synthetic=True))
        self.admin=self.app.state.admin
    def tearDown(self):self.temp.cleanup()
    def snapshot(self):
        with self.admin.store.db() as db:return db.execute('SELECT kind,id,data FROM admin_config ORDER BY kind,id').fetchall()
    def test_import_adds_exact_32_skus_and_3_therapies_with_prices_preserving_existing_state(self):
        from import_master_therapies import run
        before=self.snapshot()
        self.admin.put('template_draft','master-therapy-1',{'id':'master-therapy-1','name':'Owner custom draft'})
        with patch.object(self.admin.api,'call',side_effect=AssertionError('No remote operations')):
            result=run(self.app)
        self.assertEqual(result['master_skus'],32)
        after={(k,i):v for k,i,v in self.snapshot()}
        for k,i,v in before:self.assertEqual(after[(k,i)],v)
        self.assertEqual(self.admin.get('template_draft','master-therapy-1')['name'],'Owner custom draft')
        self.assertEqual(len(self.admin.records('master')),40)
        self.assertEqual(len(self.admin.records('therapy')),4)
        for prefix,monthly in [('SEMA',249),('TIRZ',449),('SERM',199),('METFORM',49)]:
            for months in (1,3,6,12):
                for suffix in ('','-SUB'):
                    m=self.admin.get('master',f'{prefix}-{months}M{suffix}')
                    self.assertEqual(m['offers'][0]['price'],f'{monthly*months}.00')
                    self.assertEqual(m['offers'][0]['billing_models'],[])
                    self.assertEqual(m['planning_contract']['renewal_months'],months if suffix else None)
                    self.assertIsNone(m['product_id'])
                    self.assertEqual(m['planning_contract']['shipments_per_term'],{6:2,12:4}.get(months))
                    self.assertEqual(m['planning_contract']['shipment_interval'],90 if months in (6,12) else None)
        self.assertIsNone(self.admin.owner())
        m=self.admin.get('master','SEMA-1M');m['offers'][0]['price']='260.00';self.admin.put('master','SEMA-1M',m)
        snapshot=self.snapshot();self.assertTrue(run(self.app)['already_imported']);self.assertEqual(snapshot,self.snapshot())
    def test_explicit_live_promotion_preserves_existing_skus_and_never_calls_sticky(self):
        from import_master_therapies import promote_live
        self.admin.cfg.synthetic=False
        self.admin.cfg.public_url='https://wlmd-stripe-test-0f89b1bb.fly.dev'
        self.admin.put('master','TIRZ-1M',{'sku':'TIRZ-1M','name':'Existing live configuration'})
        self.admin.put('sku','TIRZ-1M',{'sku':'TIRZ-1M','product_id':2856})
        before=self.snapshot()
        with patch.object(self.admin.api,'call',side_effect=AssertionError('No network calls')):
            result=promote_live(self.app)
        self.assertEqual(result['master_skus'],39)
        self.assertEqual(result['preserved_existing_skus'],['TIRZ-1M'])
        after={(k,i):v for k,i,v in self.snapshot()}
        for k,i,v in before:self.assertEqual(after[(k,i)],v)
        self.assertNotIn('TIRZ-1M',self.admin.get('purchase_option','weight-loss-1m')['skus'])
        self.assertEqual(len(self.admin.records('purchase_option')),20)
        saved=self.snapshot()
        self.assertTrue(promote_live(self.app)['already_imported'])
        self.assertEqual(saved,self.snapshot())
        self.assertIsNone(self.admin.owner())

    def test_live_promotion_rejects_other_hosts_and_existing_plan_collisions_atomically(self):
        from import_master_therapies import promote_live
        before=self.snapshot()
        with self.assertRaises(ValueError):promote_live(self.app)
        self.assertEqual(before,self.snapshot())
        self.admin.cfg.synthetic=False
        self.admin.cfg.public_url='https://wlmd-stripe-test-0f89b1bb.fly.dev'
        self.admin.put('purchase_option','metformin-1m',{'id':'metformin-1m','owner_value':True})
        before=self.snapshot()
        with self.assertRaises(ValueError):promote_live(self.app)
        self.assertEqual(before,self.snapshot())

    def test_test_activation_is_revision_bound_and_cannot_enable_physical_prepaid(self):
        from import_master_therapies import run
        from master import fingerprint
        from fastapi import HTTPException
        run(self.app);master=self.admin.get('master','SEMA-12M-SUB')
        configured=dict(master,product_template={'sku':master['sku'],'is_shippable':0,'taxable':0})
        configured.pop('planning_contract')
        activation={'sku':master['sku'],'master_hash':fingerprint(master),'master':configured,'payment_test_only':True}
        self.admin.put('test_catalog_activation',master['sku'],activation)
        self.assertEqual(self.admin.activated_master(master),configured)
        changed=dict(master,revision=master['revision']+1)
        with self.assertRaises(HTTPException):self.admin.activated_master(changed)
        activation['master']['product_template']['is_shippable']=1
        self.admin.put('test_catalog_activation',master['sku'],activation)
        with self.assertRaises(HTTPException):self.admin.activated_master(master)

    def test_collision_rolls_back_whole_import_and_live_environment_is_rejected(self):
        from import_master_therapies import run
        self.admin.put('sku','SERM-1M',{'sku':'SERM-1M','name':'Existing custom SKU'})
        before=self.snapshot()
        with self.assertRaises(ValueError):run(self.app)
        self.assertEqual(before,self.snapshot())
        self.admin.cfg.synthetic=False
        with self.assertRaises(ValueError):run(self.app)
        self.assertEqual(before,self.snapshot())
    def test_planning_price_can_change_but_activation_and_mapping_are_blocked(self):
        from import_master_therapies import run
        from master import MasterSKU
        from fastapi import HTTPException
        run(self.app);m=self.admin.get('master','SEMA-12M-SUB')
        request={k:v for k,v in m.items() if k in MasterSKU.model_fields}
        request['offers'][0]['price']='3000.00'
        with patch.object(self.admin.api,'call',side_effect=AssertionError('No network')):
            data,guards,_,ops,_=self.admin.prepare_master('master',request)
        self.assertEqual(data['offers'][0]['price'],'3000.00');self.assertFalse(guards or ops)
        with self.assertRaises(HTTPException):self.admin.prepare_master('master',request|{'planning_contract':None,'offers':[{'id':'upfront','name':'Bad conversion','price':'3000','billing_models':[3]}]})
        brand=self.admin.get('brand','demo-brand');brand['campaign_id']=422;brand['campaign_ids']=[422];self.admin.put('brand','demo-brand',brand)
        with self.assertRaisesRegex(HTTPException,'verify planned billing'):self.admin.prepare_master('provision',{'brand_id':'demo-brand','skus':['SEMA-12M-SUB']})
        with self.assertRaisesRegex(HTTPException,'verify planned billing'):self.admin.template_source({'id':'example','therapy_id':'weight-loss','purchase_option_ids':['weight-loss-12m']})

    def test_editing_prepaid_shipments_rebuilds_product_setup_and_keeps_renewal(self):
        from import_master_therapies import run
        from master import MasterSKU
        from pydantic import ValidationError
        from fastapi import HTTPException
        run(self.app)
        for suffix,renewal in [('',None),('-SUB',12)]:
            master=self.admin.get('master','SEMA-12M'+suffix)
            self.assertEqual(master['product_setup']['shipment_days'],[0,90,180,270])
            request={k:v for k,v in master.items() if k in MasterSKU.model_fields}
            request['planning_contract']=dict(request['planning_contract'],shipments_per_term=3,shipment_interval=120)
            data,guards,preview,ops,_=self.admin.prepare_master('master',request)
            self.assertFalse(guards or ops)
            self.assertEqual(data['product_setup']['shipment_days'],[0,120,240])
            self.assertEqual(data['product_setup']['prepaid_cycles'],3)
            self.assertEqual(data['product_setup']['upfront_price'],master['offers'][0]['price'])
            self.assertEqual(data['product_setup']['renewal_months'],renewal)
            self.assertEqual(data['product_setup']['renewal_days'],renewal*30 if renewal else None)
            self.assertEqual(data['product_setup']['per_shipment_product_price'],'996.00')
            self.assertEqual(preview['after']['product_setup'],data['product_setup'])
            self.admin.finalize_master('master',data,lambda x:x)
            self.assertEqual(self.admin.get('master',master['sku'])['product_setup']['shipment_count'],3)
            with self.assertRaises(HTTPException):self.admin.prepare_master('master',request|{'planning_contract':dict(request['planning_contract'],renewal_months=None if renewal else 12)})
            for count,days in [(0,90),(2,None),(None,90),(2,0),(2,True),(37,90)]:
                with self.assertRaises(ValidationError):self.admin.prepare_master('master',request|{'planning_contract':dict(request['planning_contract'],shipments_per_term=count,shipment_interval=days)})
        self.assertEqual(self.admin.get('master','SEMA-6M')['product_setup']['shipment_days'],[0,90])
    def test_pt141_import_has_exact_eight_skus_and_shipment_upgrade_preserves_prices_and_edits(self):
        from import_master_therapies import run,add_pt141,upgrade_shipments
        run(self.app);before=self.snapshot()
        added=add_pt141(self.app);self.assertEqual(added['master_skus'],8)
        for months in (1,3,6,12):
            for suffix in ('','-SUB'):
                m=self.admin.get('master',f'PT141-{months}M{suffix}')
                self.assertEqual(m['offers'][0]['price'],f'{months*199}.00')
                self.assertEqual(m['planning_contract']['renewal_months'],months if suffix else None)
                self.assertEqual(m['planning_contract']['shipments_per_term'],{6:2,12:4}.get(months))
        self.assertTrue(add_pt141(self.app)['already_imported'])
        # Reproduce pre-upgrade catalog records, without overwriting their prices or other fields.
        for master in self.admin.records('master'):
            if master.get('planning_contract') and master['product_duration_months'] in (6,12) and not master['sku'].startswith('PT141'):
                master['planning_contract']['shipment_interval']=None
                if master['therapy_id']!='weight-loss':master['planning_contract']['shipments_per_term']=None
                master.pop('product_setup',None)
                self.admin.put('master',master['sku'],master)
        m=self.admin.get('master','SEMA-12M');m['offers'][0]['price']='3000.00';self.admin.put('master',m['sku'],m)
        with patch.object(self.admin.api,'call',side_effect=AssertionError('No remote calls')):result=upgrade_shipments(self.app)
        self.assertEqual(result['updated_masters'],16)
        self.assertEqual(self.admin.get('master','SEMA-12M')['offers'][0]['price'],'3000.00')
        self.assertEqual(self.admin.get('master','SEMA-12M')['product_setup']['shipment_days'],[0,90,180,270])
        snapshot=self.snapshot();self.assertTrue(upgrade_shipments(self.app)['already_applied']);self.assertEqual(snapshot,self.snapshot())
        unchanged={(k,i):v for k,i,v in self.snapshot()}
        for k,i,v in before:
            if k!='master' or not (i.endswith('6M') or i.endswith('12M') or i.endswith('6M-SUB') or i.endswith('12M-SUB')):self.assertEqual(unchanged[(k,i)],v)


if __name__=='__main__':unittest.main()


class TherapyCampaignSpecTests(unittest.TestCase):
    def test_all_40_specs_charge_whole_term_and_match_exact_renewal_days(self):
        from therapy_campaign_setup import specification
        from therapy_skeletons import all_skeletons
        from decimal import Decimal
        specs=[]
        for skeleton in all_skeletons():
            for p in skeleton['products']:
                m={'name':p['sku'],'offers':[{'price':p['price']}]}
                spec=specification(p,m);specs.append(spec)
                self.assertEqual(Decimal(spec['unit'])*(spec['cycles'] or 1),Decimal(p['price']))
                if p['renewal_months']:self.assertEqual(spec['days']*(spec['cycles'] or 1),p['duration_months']*30)
                self.assertEqual(spec['configuration'].get('prepaid',{}).get('is_subscription',0),int(bool(spec['cycles'] and p['renewal_months'])))
        self.assertEqual(len(specs),40)
    def test_incompatible_custom_shipments_cannot_silently_change_renewal_term(self):
        from therapy_campaign_setup import specification
        p={'sku':'SEMA-6M-SUB','duration_months':6}
        m={'name':'Six-month','offers':[{'price':'1494.00'}],'planning_contract':{'renewal_months':6,'shipments_per_term':3,'shipment_interval':90}}
        with self.assertRaises(ValueError):specification(p,m)

    def test_uncertain_external_write_cannot_be_retried(self):
        from therapy_campaign_setup import Setup
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            setup=Setup.__new__(Setup);setup.path=Path(directory)/'journal.json';setup.state={'operations':{}}
            setup.api=Mock();setup.api.call.side_effect=TimeoutError('uncertain')
            with self.assertRaises(TimeoutError):setup.write('new-offer','POST','/api/v2/offers',{'name':'Synthetic'})
            with self.assertRaises(ValueError):setup.write('new-offer','POST','/api/v2/offers',{'name':'Synthetic'})
            self.assertEqual(setup.api.call.call_count,1)

    def test_full_campaign_setup_publishes_four_ready_private_checkouts_idempotently(self):
        from app import create_app,Settings
        from qa.fake_master import MasterSticky
        from therapy_campaign_setup import Setup,BRAND
        from import_master_therapies import run,add_pt141
        from fastapi.testclient import TestClient
        with tempfile.TemporaryDirectory() as directory:
            fake=MasterSticky();app=create_app(Settings(public_url='https://localhost',state_dir=Path(directory),authorization_verified=True),fake)
            admin=app.state.admin;admin.cfg.synthetic=True
            run(app);add_pt141(app);admin.cfg.synthetic=False
            admin.put('brand','campaign-422',{'id':'campaign-422','name':'Existing','campaign_id':422,'campaign_ids':[422],'color':'#245844'})
            before={k:admin.records(k) for k in ('brand','offering','assignment','link')}
            setup=Setup.__new__(Setup);setup.admin=admin;setup.api=fake;setup.path=Path(directory)/'journal.json';setup.state={'id':'test','operations':{},'renewal_proof':{'verified':True}}
            setup.check_campaign=lambda:fake.detail('/api/v2/campaigns/422')
            provisioned=setup.provision();self.assertEqual(provisioned['created_products'],40)
            self.assertEqual(fake.count('/products'),40);self.assertEqual(fake.count('/offers'),40)
            published=setup.publish();self.assertEqual(len(published['checkouts']),4)
            self.assertEqual(len(published['quote_checks']),40)
            self.assertEqual(len(admin.records('test_catalog_activation')),40)
            self.assertEqual(len(admin.site_state()[0]['checkouts']),4)
            self.assertTrue(all(c['status']=='ready' for c in admin.site_state()[0]['checkouts']))
            for k,rows in before.items():
                for old in rows:self.assertIn(old,admin.records(k))
            customer=TestClient(app,base_url='https://localhost')
            for plan in admin.plan_state():
                customer.get(plan['url']);data=customer.get('/api/plans/'+plan['id']).json()
                self.assertTrue(data['paymentTestOnly']);self.assertTrue(all(e['available'] for e in data['entries']))
                self.assertTrue(all('renewal' in o for e in data['entries'] for o in e['options'] if o.get('prepaidCycles')))
            self.assertEqual(fake.count('/new_order'),0);self.assertEqual(fake.count('/authorize_payment'),0)
            self.assertTrue(setup.publish()['already_published']);self.assertEqual(fake.count('/products'),40)
            customer.close()
