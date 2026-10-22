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


if __name__=='__main__':unittest.main()
