"""Connection reuse must never share checkout identity or retry a payment."""
from email.message import Message
import http.client
import json
import ssl
import threading
import time
import unittest
from unittest.mock import patch

from demo.session_api import CheckoutTransport, PUBLIC_UPSTREAM, UpstreamError


class Response:
    def __init__(self,body=b'{}',status=200,cookies=(),will_close=False,read_error=None):
        self.body=body;self.status=status;self.will_close=will_close;self.read_error=read_error
        self.headers=Message()
        for cookie in cookies:self.headers.add_header('Set-Cookie',cookie)

    def read(self):
        if self.read_error:raise self.read_error
        return self.body


class Connection:
    def __init__(self,responses=(),request_error=None):
        self.responses=list(responses);self.request_error=request_error
        self.requests=[];self.closed=False

    def request(self,method,path,body,headers):
        self.requests.append((method,path,body,dict(headers)))
        if self.request_error:raise self.request_error

    def getresponse(self):
        return self.responses.pop(0)

    def close(self):self.closed=True


def row(cookie=''):
    return {'cookies':json.dumps({'__Host-checkout-browser':cookie} if cookie else {}),
            'csrf':'synthetic-csrf','attempt':'synthetic-attempt','link_id':'choice-'+'a'*32}


class CheckoutConnectionPoolTests(unittest.TestCase):
    def test_dedicated_origin_and_loopback_are_explicit_server_configuration(self):
        origin='https://fortifyhp-0f89b1bb.fly.dev'
        with self.assertRaises(ValueError):CheckoutTransport(origin)
        with self.assertRaises(ValueError):CheckoutTransport(origin,approved_origins=(origin,),loopback_port='8080')
        connection=Connection([Response()])
        with patch('demo.session_api.http.client.HTTPConnection',return_value=connection) as local, \
                patch('demo.session_api.http.client.HTTPSConnection') as remote:
            transport=CheckoutTransport(origin,approved_origins=(origin,),loopback_port=8080)
            transport.call(row(),'POST','/api/quote',{},client_ip='203.0.113.42')
            self.assertEqual(local.call_args.args,('127.0.0.1',8080))
            self.assertEqual(connection.requests[0][3]['Origin'],origin)
            self.assertEqual(connection.requests[0][3]['Host'],'fortifyhp-0f89b1bb.fly.dev')
            self.assertEqual(connection.requests[0][3]['Fly-Client-IP'],'203.0.113.42')
            self.assertFalse(remote.called)
            transport.close()

    def test_intake_patch_uses_receipt_csrf_and_preserves_answers(self):
        connection=Connection([Response(b'{"revision":1}')])
        with patch('demo.session_api.http.client.HTTPSConnection',return_value=connection):
            transport=CheckoutTransport()
            data,_=transport.call(row('customer'),'PATCH','/api/post-checkout-intake',{'revision':0,'answers':{'allergies':'Synthetic only'}})
            self.assertEqual(data,{'revision':1})
            sent=connection.requests[0]
            self.assertEqual(sent[0],'PATCH')
            self.assertIn('X-CSRF-Token',sent[3])
            self.assertEqual(sent[3]['Origin'],transport.upstream)
            transport.close()

    def test_portal_enrollment_uses_the_existing_attempt_and_fixed_upstream(self):
        connection=Connection([Response(b'{"site_id":"fortifyhp"}')])
        with patch('demo.session_api.http.client.HTTPSConnection',return_value=connection):
            transport=CheckoutTransport()
            data,_=transport.call(row('customer'),'POST','/api/portal-enrollment',{})
            self.assertEqual(data,{'site_id':'fortifyhp'})
            sent=connection.requests[0]
            self.assertEqual(sent[1],'/api/portal-enrollment?link_id=choice-'+'a'*32)
            self.assertEqual(sent[3]['X-Checkout-Attempt'],'synthetic-attempt')
            self.assertEqual(sent[3]['Cookie'],'__Host-checkout-browser=customer')
            transport.close()

    def test_connection_reused_without_cookie_or_identity_leakage(self):
        connection=Connection([
            Response(cookies=['__Host-checkout-browser=first; Secure',
                              'owner_session=must-not-copy; Secure']),
            Response(),Response()])
        with patch('demo.session_api.http.client.HTTPSConnection',return_value=connection) as factory:
            transport=CheckoutTransport()
            _,first_cookies=transport.call(row(),'GET','/api/config')
            transport.call(row('second'),'GET','/api/status')
            transport.call(row(),'POST','/api/quote',{'synthetic':True})
            self.assertEqual(factory.call_count,1)
            args,kwargs=factory.call_args
            self.assertEqual(args,('wlmd-stripe-test-0f89b1bb.fly.dev',))
            self.assertEqual(kwargs['context'].verify_mode,ssl.CERT_REQUIRED)
            self.assertTrue(kwargs['context'].check_hostname)
            self.assertEqual(first_cookies,{'__Host-checkout-browser':'first'})
            self.assertEqual([r[3]['Cookie'] for r in connection.requests],['','__Host-checkout-browser=second',''])
            self.assertEqual(connection.requests[2][3]['Origin'],PUBLIC_UPSTREAM)
            self.assertNotIn('Authorization',connection.requests[2][3])
            self.assertNotIn('Fly-Client-IP',connection.requests[2][3])
            self.assertEqual(connection.requests[2][1],'/api/quote?link_id=choice-'+'a'*32)
            transport.close()
            self.assertTrue(connection.closed)

    def test_failed_reused_financial_request_is_never_retried(self):
        connection=Connection([Response()]);replacement=Connection([Response()])
        with patch('demo.session_api.http.client.HTTPSConnection',side_effect=[connection,replacement]) as factory:
            transport=CheckoutTransport()
            transport.call(row(),'GET','/api/config')
            connection.request_error=http.client.RemoteDisconnected('stale socket')
            with self.assertRaises(UpstreamError):transport.call(row(),'POST','/api/authorize',{})
            self.assertEqual(factory.call_count,1)
            self.assertEqual(len(connection.requests),2)
            self.assertTrue(connection.closed)
            # A distinct later call may allocate a healthy connection.
            transport.call(row(),'GET','/api/status')
            self.assertEqual(factory.call_count,2)
            transport.close()

    def test_interrupted_response_is_discarded_without_retry(self):
        connection=Connection([Response(read_error=http.client.IncompleteRead(b'partial'))])
        with patch('demo.session_api.http.client.HTTPSConnection',return_value=connection) as factory:
            transport=CheckoutTransport()
            with self.assertRaises(UpstreamError):transport.call(row(),'POST','/api/capture',{})
            self.assertEqual(factory.call_count,1)
            self.assertEqual(len(connection.requests),1)
            self.assertTrue(connection.closed)
            self.assertEqual(transport._count,0)

    def test_server_connection_close_is_not_reused(self):
        first=Connection([Response(will_close=True)]);second=Connection([Response()])
        with patch('demo.session_api.http.client.HTTPSConnection',side_effect=[first,second]) as factory:
            transport=CheckoutTransport()
            transport.call(row(),'GET','/api/config');transport.call(row(),'GET','/api/status')
            self.assertEqual(factory.call_count,2)
            self.assertTrue(first.closed)
            transport.close()

    def test_expired_idle_connection_is_closed_before_any_new_request(self):
        first=Connection([Response()]);second=Connection([Response()])
        with patch('demo.session_api.http.client.HTTPSConnection',side_effect=[first,second]) as factory:
            transport=CheckoutTransport(idle_timeout=1)
            transport.call(row(),'GET','/api/config')
            transport._idle[0]=(first,time.monotonic()-2)
            transport.call(row(),'POST','/api/authorize',{})
            self.assertEqual(factory.call_count,2)
            self.assertEqual(len(first.requests),1)
            self.assertTrue(first.closed)
            transport.close()

    def test_redirect_never_followed_and_http_error_keeps_original_status(self):
        connection=Connection([Response(status=307),Response(b'{"detail":"Quote changed"}',status=409),
                               Response(b'not json',status=503)])
        with patch('demo.session_api.http.client.HTTPSConnection',return_value=connection):
            transport=CheckoutTransport()
            with self.assertRaises(UpstreamError) as caught:transport.call(row(),'POST','/api/authorize',{})
            self.assertIn('redirect',caught.exception.detail)
            self.assertEqual(len(connection.requests),1)
            with self.assertRaises(UpstreamError) as caught:transport.call(row(),'POST','/api/authorize',{})
            self.assertEqual(caught.exception.status,409)
            self.assertEqual(caught.exception.detail,'Quote changed')
            with self.assertRaises(UpstreamError) as caught:transport.call(row(),'GET','/api/config')
            self.assertEqual(caught.exception.status,503)
            self.assertEqual(caught.exception.detail,'Checkout request was rejected')
            transport.close()

    def test_bounded_pool_waits_for_exclusive_connection_ownership(self):
        entered=threading.Event();release=threading.Event();errors=[]
        class BlockingResponse(Response):
            def read(self):
                entered.set()
                if not release.wait(2):raise TimeoutError()
                return super().read()
        connection=Connection([BlockingResponse(),Response()])
        with patch('demo.session_api.http.client.HTTPSConnection',return_value=connection) as factory:
            transport=CheckoutTransport(max_connections=1)
            def call(cookie):
                try:transport.call(row(cookie),'GET','/api/status')
                except Exception as exc:errors.append(exc)
            first=threading.Thread(target=call,args=('one',));second=threading.Thread(target=call,args=('two',))
            first.start();self.assertTrue(entered.wait(2));second.start()
            try:
                self.assertEqual(factory.call_count,1)
                self.assertEqual(len(connection.requests),1)
            finally:
                release.set();first.join(2);second.join(2);transport.close()
            self.assertFalse(first.is_alive());self.assertFalse(second.is_alive())
            self.assertEqual(errors,[])
            self.assertEqual(len(connection.requests),2)
            self.assertEqual(factory.call_count,1)
            self.assertEqual([r[3]['Cookie'] for r in connection.requests],['__Host-checkout-browser=one','__Host-checkout-browser=two'])

    def test_pool_capacity_timeout_does_not_send_request(self):
        connection=Connection()
        with patch('demo.session_api.http.client.HTTPSConnection',return_value=connection) as factory:
            transport=CheckoutTransport(max_connections=1,timeout=.01)
            owned=transport._acquire()
            with self.assertRaises(UpstreamError):transport.call(row(),'POST','/api/capture',{})
            self.assertEqual(factory.call_count,1);self.assertEqual(connection.requests,[])
            transport._release(owned,False);transport.close()

    def test_path_and_cookie_validation_happens_before_connection_checkout(self):
        with patch('demo.session_api.http.client.HTTPSConnection') as factory:
            transport=CheckoutTransport()
            with self.assertRaises(ValueError):transport.call(row(),'POST','/api/v1/new_order',{})
            bad=row();bad['cookies']='{"admin":"forbidden"}'
            with self.assertRaises(ValueError):transport.call(bad,'GET','/api/config')
            factory.assert_not_called()
            transport.close()


if __name__=='__main__':unittest.main()
