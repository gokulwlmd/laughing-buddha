"""Lifecycle warming removes the idle-catalog penalty without relaxing expiry."""
import threading
import unittest
from fastapi.testclient import TestClient
from demo.public import create_public_app, CATALOG_MAX_AGE_SECONDS
from test_site_api_public import fixture


class WarmupTests(unittest.TestCase):
    def test_lifespan_fetches_before_customer_and_retains_hard_expiry(self):
        started=threading.Event();finished=threading.Event();now=[1000];calls=[];fail=[False]
        def read():
            calls.append(1);started.set()
            if fail[0]:raise RuntimeError('upstream unavailable')
            finished.set();return fixture()
        app=create_public_app('https://demo.example',read_catalog=read,clock=lambda:now[0],warm_catalog=True)
        with TestClient(app,base_url='https://demo.example') as client:
            self.assertTrue(started.wait(2));self.assertTrue(finished.wait(2))
            result=client.get('/api/v1/sites/payment-test/plans')
            self.assertEqual(result.status_code,200);self.assertEqual(len(calls),1)
            self.assertRegex(result.headers['server-timing'],r'^app;dur=[0-9.]+$')
            fail[0]=True;now[0]+=CATALOG_MAX_AGE_SECONDS+1
            self.assertEqual(client.get('/api/v1/sites/payment-test/plans').status_code,503)

    def test_injected_catalog_has_no_background_calls_by_default(self):
        calls=[]
        def read():calls.append(1);return fixture()
        app=create_public_app('https://demo.example',read_catalog=read)
        with TestClient(app,base_url='https://demo.example') as client:
            self.assertEqual(client.get('/health').status_code,200)
            self.assertEqual(calls,[])
