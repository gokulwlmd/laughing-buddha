"""Payment uses the engine's verified route without a duplicate catalog request."""
import unittest
from unittest.mock import patch
from demo.session_api import UpstreamError
import test_site_session_api as fixtures
from app import Sticky

class PaymentPreparationTests(unittest.TestCase):
    setUp=fixtures.SessionApiTests.setUp
    tearDown=fixtures.SessionApiTests.tearDown
    create=fixtures.SessionApiTests.create
    configured=fixtures.SessionApiTests.configured
    quoted=fixtures.SessionApiTests.quoted
    prepared=fixtures.SessionApiTests.prepared

    def test_payment_uses_one_fresh_configuration_and_returned_key(self):
        path,headers,_,quote=self.quoted()
        self.fake.reads.clear();self.transport.calls.clear()
        result=self.client.post(path+'/payment',headers=headers,json={'quote_id':quote['quote_id']})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['publishable_key'],'pk_live_placeholder')
        self.assertEqual([p for _,p,_,_ in self.transport.calls],['/api/status','/api/authorize'])
        for p in ('/api/v2/campaigns/422','/api/v2/offers/706','/api/v2/products/54537','/api/v2/providers/payment/profiles/254'):
            self.assertEqual(self.fake.reads.count(p),1,p)
        self.assertEqual(self.fake.count('/authorize_payment'),1)

    def test_both_resume_routes_reuse_original_intent_without_duplicate_config(self):
        path,headers,data,payment=self.prepared()
        quote_id=self.store.read(data['session_id'])['quote_id']
        for endpoint,body in (('/payment',{'quote_id':quote_id}),('/resume',{})):
            self.transport.calls.clear();self.fake.reads.clear()
            result=self.client.post(path+endpoint,headers=headers,json=body)
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.json(),payment)
            self.assertNotIn('/api/config',[p for _,p,_,_ in self.transport.calls])
            self.assertEqual(self.fake.reads.count('/api/v2/campaigns/422'),1)
        self.assertEqual(self.fake.count('/authorize_payment'),1)

    def test_status_failure_stops_before_authorization(self):
        path,headers,_,quote=self.quoted();self.transport.fail_before='/api/status'
        r=self.client.post(path+'/payment',headers=headers,json={'quote_id':quote['quote_id']})
        self.assertEqual(r.status_code,502)
        self.assertEqual(self.fake.count('/authorize_payment'),0)

    def test_fresh_gateway_failure_still_prevents_authorization(self):
        path,headers,_,quote=self.quoted();self.fake.link_gateway=999
        r=self.client.post(path+'/payment',headers=headers,json={'quote_id':quote['quote_id']})
        self.assertEqual(r.status_code,409,r.text)
        self.assertEqual(self.fake.count('/authorize_payment'),0)

    def test_missing_verified_key_is_held_and_never_reauthorized(self):
        path,headers,data,quote=self.quoted();original=self.transport.call
        def malformed(row,method,endpoint,body=None,client_ip=None):
            result,cookies=original(row,method,endpoint,body,client_ip)
            if endpoint=='/api/authorize':result.pop('publishableKey',None)
            return result,cookies
        self.transport.call=malformed
        r=self.client.post(path+'/payment',headers=headers,json={'quote_id':quote['quote_id']})
        self.assertEqual(r.status_code,502)
        self.assertEqual(self.store.read(data['session_id'])['held'],'authorization_unknown')
        self.assertEqual(self.fake.count('/authorize_payment'),1)
        r=self.client.post(path+'/payment',headers=headers,json={'quote_id':quote['quote_id']})
        self.assertEqual(r.status_code,409)
        self.assertEqual(self.fake.count('/authorize_payment'),1)

class SafeTimingTests(unittest.TestCase):
    def test_logs_operation_and_time_without_payload_or_response(self):
        for failure in (False,True):
            with patch.object(Sticky,'_call',side_effect=RuntimeError('PRIVATE') if failure else None,return_value={'token':'PRIVATE'}):
                with self.assertLogs('uvicorn.error',level='INFO') as logs:
                    try:Sticky().call('POST','/api/v1/new_order',{'email':'PRIVATE','transactionId':'PRIVATE'})
                    except RuntimeError:pass
                text=' '.join(logs.output)
                self.assertIn('operation=create_order',text)
                self.assertIn('duration_ms=',text)
                self.assertNotIn('PRIVATE',text)
                self.assertIn('outcome='+('error' if failure else 'response'),text)

if __name__=='__main__':unittest.main()
