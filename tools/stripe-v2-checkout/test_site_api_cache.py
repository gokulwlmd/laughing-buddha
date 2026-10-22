"""Display reuse must never cache payment state or weaken live payment checks."""
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest

from fastapi.testclient import TestClient
from demo.public import create_public_app
from demo.session_api import Configuration,DisplayConfigurationCache,UpstreamError
import test_site_session_api as fixture


class ConfigurationCacheTests(unittest.TestCase):
    def value(self):
        return Configuration(publishable_key='pk_test_public',currency='usd',countries=[{'code':'US','name':'United States'}],shipping=[],plan={'basePrice':'2.00'},payment_test_only=True)

    def test_concurrent_followers_share_one_load_and_check_their_own_access(self):
        cache=DisplayConfigurationCache();started=threading.Event();release=threading.Event();follower=threading.Event()
        loads=[];access=[]
        def load():
            loads.append(1);started.set();self.assertTrue(release.wait(3));return self.value()
        def second():
            follower.set();return cache.get(('link','selection'),load,lambda:access.append('second'))
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(cache.get,('link','selection'),load,lambda:access.append('first'))
            self.assertTrue(started.wait(3));other=pool.submit(second)
            self.assertTrue(follower.wait(3));release.set()
            self.assertEqual(first.result().model_dump(),other.result().model_dump())
        self.assertEqual(loads,[1]);self.assertEqual(access,['second'])

    def test_expiry_failure_never_returns_stale_data_and_capacity_is_bounded(self):
        now=[0];cache=DisplayConfigurationCache(clock=lambda:now[0],limit=2)
        for key in ('a','b','c'):cache.get((key,'selection'),self.value,lambda:None)
        self.assertEqual(len(cache.entries),2);self.assertNotIn(('a','selection'),cache.entries)
        now[0]=60
        def failed():raise UpstreamError()
        with self.assertRaises(UpstreamError):cache.get(('c','selection'),failed,lambda:None)
        self.assertNotIn(('c','selection'),cache.entries)

    def test_callers_cannot_mutate_shared_data_or_cross_selection_boundaries(self):
        cache=DisplayConfigurationCache();loads=[]
        def load():loads.append(1);return self.value()
        first=cache.get(('link','one'),load,lambda:None);first.plan['basePrice']='999.00'
        self.assertEqual(cache.get(('link','one'),load,lambda:None).plan['basePrice'],'2.00')
        cache.get(('link','two'),load,lambda:None)
        self.assertEqual(len(loads),2)


class CachedConfigurationRouteTests(unittest.TestCase):
    # Reuse only fixture/helper methods; inherited tests would run twice.
    create=fixture.SessionApiTests.create
    configured=fixture.SessionApiTests.configured
    quoted=fixture.SessionApiTests.quoted
    prepared=fixture.SessionApiTests.prepared
    tearDown=fixture.SessionApiTests.tearDown

    def setUp(self):
        fixture.SessionApiTests.setUp(self)
        self.client.close()
        self.api=create_public_app(fixture.ORIGIN,read_catalog=lambda:self.catalog,clock=lambda:self.now,session_store=self.store,transport=self.transport)
        self.client=TestClient(self.api,base_url=fixture.ORIGIN)

    def count(self,path):return sum(call[1]==path for call in self.transport.calls)

    def test_two_sessions_share_only_display_data_and_recheck_link_access(self):
        a,ha,da=self.configured();b,hb,db=self.create()
        self.assertEqual(self.client.get(b+'/configuration',headers=hb).status_code,200)
        self.assertEqual(self.count('/api/config'),1);self.assertEqual(self.count('/api/status'),1)
        self.assertEqual(self.client.get(b+'/configuration',headers=ha).status_code,401)
        link=self.engine.state.admin.get('link',self.link_id)
        self.engine.state.admin.put('link',self.link_id,link|{'enabled':False})
        self.assertEqual(self.client.get(a+'/configuration',headers=ha).status_code,404)
        self.assertEqual(self.count('/api/config'),1)

    def test_expired_configuration_refresh_failure_is_not_hidden(self):
        path,headers,_=self.configured();self.now+=61
        self.transport.fail_before='/api/config'
        self.assertEqual(self.client.get(path+'/configuration',headers=headers).status_code,502)
        self.assertEqual(self.count('/api/config'),2)
        self.assertEqual(self.client.get(path+'/configuration',headers=headers).status_code,200)
        self.assertEqual(self.count('/api/config'),3)

    def test_cached_display_does_not_allow_new_quote_after_product_is_disabled(self):
        path,headers,_=self.configured();self.fake.archived=True
        self.assertEqual(self.client.get(path+'/configuration',headers=headers).status_code,200)
        self.assertEqual(self.client.post(path+'/quote',headers=headers,json={'contact':fixture.CONTACT,'shipping_id':2}).status_code,502)
        self.assertEqual(self.fake.count('/calculate'),0)
        self.assertEqual(self.fake.count('/authorize_payment'),0)

    def test_payment_and_resume_still_fetch_fresh_configuration_and_reject_drift(self):
        path,headers,data,payment=self.prepared()
        self.assertEqual(self.count('/api/config'),2)
        original=self.fake.detail
        def changed(endpoint):
            value=original(endpoint)
            if '/profiles/' in endpoint:value['fields']['account_fields']['publishable_key']='pk_test_changed'
            return value
        self.fake.detail=changed
        self.assertEqual(self.client.get(path+'/configuration',headers=headers).json()['publishable_key'],'pk_live_placeholder')
        response=self.client.post(path+'/resume',headers=headers,json={})
        self.assertEqual(response.status_code,409);self.assertNotIn('client_secret',response.text)
        self.assertEqual(self.count('/api/config'),3)
        self.assertEqual(self.fake.count('/authorize_payment'),1)


if __name__=='__main__':unittest.main()
