"""Independent public checkout visits remain browser-owned and preserve old attempts."""
import unittest
from fastapi.testclient import TestClient
import test_admin as admin_helpers
from test_checkout import ORIGIN,CONTACT

class VisitTests(unittest.TestCase):
    setUp=admin_helpers.AdminTests.setUp
    tearDown=admin_helpers.AdminTests.tearDown
    post=admin_helpers.AdminTests.post
    review=admin_helpers.AdminTests.review
    apply=admin_helpers.AdminTests.apply
    seed=admin_helpers.AdminTests.seed
    link_data=admin_helpers.AdminTests.link_data
    publish=admin_helpers.AdminTests.publish
    def visitor(self):
        c=TestClient(self.app,base_url=ORIGIN);c.get('/c/test-link')
        context=c.get('/api/checkout-context',params={'link_id':'test-link'}).json()
        headers={'Origin':ORIGIN,'X-CSRF-Token':context['csrfToken']}
        return c,headers
    def start(self,c,h):
        r=c.post('/api/start-checkout',params={'link_id':'test-link'},headers=h,json={});self.assertEqual(r.status_code,200,r.text)
        return r.json()['attemptId']
    def test_new_visit_does_not_reuse_or_reset_held_attempt_and_reload_stays_bound(self):
        self.publish();c,h=self.visitor();old=self.start(c,h);self.app.state.store.claim('new','authorization_pending',old)
        new=self.start(c,h);self.assertNotEqual(old,new)
        self.assertEqual(self.app.state.store.read(old)['status'],'authorization_pending')
        for key,status in ((old,'authorization_pending'),(new,'new')):
            r=c.get('/api/status',params={'link_id':'test-link'},headers={'X-Checkout-Attempt':key});self.assertEqual(r.status_code,200);self.assertEqual(r.json()['status'],status)
        self.assertEqual(self.fake.count('/authorize_payment'),0);self.assertEqual(self.fake.count('/new_order'),0)
    def test_another_browser_cannot_read_quote_or_resume_someone_elses_visit(self):
        self.publish();a,h=self.visitor();owned=self.start(a,h);b,other=self.visitor();self.start(b,other)
        headers=other|{'X-Checkout-Attempt':owned}
        self.assertEqual(b.get('/api/status',params={'link_id':'test-link'},headers=headers).status_code,409)
        self.assertEqual(b.post('/api/resume',params={'link_id':'test-link'},headers=headers,json={}).status_code,409)
        self.assertEqual(b.post('/api/quote',params={'link_id':'test-link'},headers=headers,json={'contact':CONTACT,'selection':'706:54537:2','shipping_id':2}).status_code,409)
        self.assertFalse(self.app.state.store.read(owned)['contact'])
    def test_start_requires_link_access_origin_csrf_and_browser_cookie(self):
        self.publish('private');c=TestClient(self.app,base_url=ORIGIN)
        self.assertEqual(c.get('/api/checkout-context',params={'link_id':'test-link'}).status_code,401)
        self.assertEqual(c.post('/api/start-checkout',params={'link_id':'test-link'},json={}).status_code,401)
        link=self.app.state.admin.get('link','test-link');c.get('/c/test-link?access='+self.app.state.admin.private_token(link));c.get('/c/test-link')
        csrf=c.get('/api/checkout-context',params={'link_id':'test-link'}).json()['csrfToken']
        self.assertEqual(c.post('/api/start-checkout',params={'link_id':'test-link'},headers={'Origin':'https://bad.example','X-CSRF-Token':csrf},json={}).status_code,403)
        self.assertEqual(c.post('/api/start-checkout',params={'link_id':'test-link'},headers={'Origin':ORIGIN},json={}).status_code,403)
    def test_visit_is_pinned_to_its_link_and_only_browser_hash_is_stored(self):
        self.publish();c,h=self.visitor();owned=self.start(c,h)
        self.assertEqual(c.get('/api/status',headers={'X-Checkout-Attempt':owned}).status_code,401)
        self.assertNotEqual(self.app.state.store.visitor(owned),c.cookies.get('__Host-checkout-browser'))
        self.assertEqual(len(self.app.state.store.visitor(owned)),64)
    def test_completed_visit_successor_is_owned_and_idempotent(self):
        self.publish();c,h=self.visitor();old=self.start(c,h);self.app.state.store.claim('new','captured',old,order_id='12345')
        headers=h|{'X-Checkout-Attempt':old};params={'link_id':'test-link'}
        first=c.post('/api/new-purchase',params=params,headers=headers,json={'previous_attempt_id':old});second=c.post('/api/new-purchase',params=params,headers=headers,json={'previous_attempt_id':old})
        self.assertEqual(first.status_code,200);self.assertEqual(first.json(),second.json());new=first.json()['attemptId']
        self.assertEqual(self.app.state.store.visitor(new),self.app.state.store.visitor(old))
        self.assertEqual(c.get('/api/status',params=params,headers={'X-Checkout-Attempt':new}).json()['status'],'new')
        self.assertEqual(self.app.state.store.read(old)['order_id'],'12345')
