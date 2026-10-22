"""Two-call demo is isolated, server-priced, and cannot execute a payment."""
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from demo.site_api import DemoSettings, create_demo_app, create_frontend_app


class SiteApiDemoTests(unittest.TestCase):
    def setUp(self):
        self.cfg=DemoSettings();self.now=1000
        self.app=create_demo_app(self.cfg,clock=lambda:self.now)
        self.client=TestClient(self.app,base_url=self.cfg.api_origin)
        self.path='/api/v1/sites/willow-health'
        self.body={'plan_id':'sema-6m-sub','return_url':self.cfg.frontend_origin+'/complete'}

    def test_catalog_has_exact_upfront_terms_and_independent_site_prices(self):
        a=self.client.get(self.path+'/plans').json()
        b=self.client.get('/api/v1/sites/harbor-wellness/plans').json()
        self.assertEqual(len(a['plans']),16)
        for site in (a,b):
            for p in site['plans']:
                self.assertEqual(p['renewal_days'],p['duration_months']*30 if p['purchase_type']=='subscription' else None)
                self.assertEqual(p['shipment_days'],{1:[0],3:[0],6:[0,90],12:[0,90,180,270]}[p['duration_months']])
        self.assertEqual(next(p['price'] for p in a['plans'] if p['plan_id']=='sema-6m-sub'),'1494.00')
        self.assertEqual(next(p['price'] for p in b['plans'] if p['plan_id']=='sema-6m-sub'),'1643.40')
        self.assertEqual(self.client.get('/api/v1/sites/unknown/plans').status_code,404)

    def test_two_calls_open_a_branded_checkout_and_finish_returns_without_order(self):
        with patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('No upstream network')):
            self.assertEqual(self.client.get(self.path+'/plans').status_code,200)
            response=self.client.post(self.path+'/checkout',json=self.body)
            self.assertEqual(response.status_code,201)
            url=response.json()['checkout_url']
            page=self.client.get(url)
            self.assertIn('Willow Health',page.text)
            self.assertIn('1494.00',page.text)
            self.assertNotIn('type="password"',page.text)
            result=self.client.post(url+'/finish',follow_redirects=False)
            self.assertEqual(result.status_code,303)
            self.assertEqual(result.headers['location'],self.body['return_url'])
            again=self.client.post(url+'/finish',follow_redirects=False)
            self.assertEqual(again.headers['location'],self.body['return_url'])

    def test_client_cannot_override_price_gateway_campaign_or_unknown_plan(self):
        for field in ('price','amount','gateway_id','campaign_id','stripe_secret'):
            self.assertEqual(self.client.post(self.path+'/checkout',json=self.body|{field:'tampered'}).status_code,422)
        self.assertEqual(self.client.post(self.path+'/checkout',json=self.body|{'plan_id':'unknown'}).status_code,404)
        self.assertEqual(self.client.post('/api/v1/sites/unknown/checkout',json=self.body).status_code,404)

    def test_return_url_and_cross_origin_requests_are_restricted(self):
        for url in ('https://evil.example/complete',self.cfg.frontend_origin+'/other',self.cfg.frontend_origin+'/complete?next=evil',self.cfg.frontend_origin+'/complete#evil','javascript:alert(1)'):
            self.assertEqual(self.client.post(self.path+'/checkout',json=self.body|{'return_url':url}).status_code,422)
        self.assertEqual(self.client.post(self.path+'/checkout',json=self.body,headers={'Origin':'https://evil.example'}).status_code,403)
        r=self.client.options(self.path+'/checkout',headers={'Origin':self.cfg.frontend_origin,'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type'})
        self.assertEqual(r.headers['access-control-allow-origin'],self.cfg.frontend_origin)
        denied=self.client.options(self.path+'/checkout',headers={'Origin':'https://evil.example','Access-Control-Request-Method':'POST'})
        self.assertNotIn('access-control-allow-origin',denied.headers)

    def test_sessions_are_independent_expire_and_do_not_expose_each_other(self):
        a=self.client.post(self.path+'/checkout',json=self.body).json()['checkout_url']
        b=self.client.post('/api/v1/sites/harbor-wellness/checkout',json=self.body).json()['checkout_url']
        self.assertNotEqual(a,b)
        self.assertIn('1643.40',self.client.get(b).text)
        self.assertNotIn('1643.40',self.client.get(a).text)
        self.now+=self.cfg.session_seconds
        self.assertEqual(self.client.get(a).status_code,410)
        self.assertEqual(self.client.post(b+'/finish').status_code,410)

    def test_each_swagger_spec_has_only_its_two_site_endpoints(self):
        for site in ('willow-health','harbor-wellness'):
            response=self.client.get(f'/sites/{site}/openapi.json')
            spec=response.json()
            self.assertEqual(set(spec['paths']),{f'/api/v1/sites/{site}/plans',f'/api/v1/sites/{site}/checkout'})
            self.assertNotIn('/api/admin',response.text)
            self.assertNotIn('STICKY_API_PASSWORD',response.text)
            self.assertEqual(self.client.get(f'/sites/{site}/docs').status_code,200)
        self.assertEqual(self.client.get('/sites/unknown/openapi.json').status_code,404)

    def test_standalone_frontend_and_demo_have_no_payment_or_admin_routes(self):
        frontend=TestClient(create_frontend_app(self.cfg))
        self.assertIn(self.cfg.api_origin,frontend.get('/').text)
        self.assertEqual(frontend.get('/complete').status_code,200)
        for route in ('/api/authorize','/api/capture','/api/admin/state','/admin'):
            self.assertEqual(self.client.post(route,json={}).status_code,404)
        self.assertEqual(self.client.get('/api/v1/sites/willow-health/plans').headers['cache-control'],'no-store')
