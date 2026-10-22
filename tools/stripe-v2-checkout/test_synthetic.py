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
                    if prefix in ('SERM','METFORM'):self.assertIsNone(m['planning_contract']['shipments_per_term'])
        self.assertIsNone(self.admin.owner())
        m=self.admin.get('master','SEMA-1M');m['offers'][0]['price']='260.00';self.admin.put('master','SEMA-1M',m)
        snapshot=self.snapshot();self.assertTrue(run(self.app)['already_imported']);self.assertEqual(snapshot,self.snapshot())
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


if __name__=='__main__':unittest.main()
