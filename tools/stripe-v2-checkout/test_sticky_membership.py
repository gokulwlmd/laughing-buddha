"""Offline Sticky membership contract and receipt/auth isolation checks."""
import os
import unittest
from unittest.mock import patch
from fastapi import HTTPException
import test_member_portal as member

class MembershipFake:
    def __init__(self, original):
        self.original=original; self.members={}; self.calls=[]; self.fail_after=None; self.active=True
    def __call__(self, method, path, body=None):
        if '/member_' not in path: return self.original(method,path,body)
        name=path.rsplit('/',1)[-1];self.calls.append((name,dict(body)))
        email=body.get('email');saved=self.members.get(email)
        if name=='member_view':return {'response_code':100,'data':saved['identity']} if saved else {'response_code':4003}
        if name=='member_create':
            if saved:return {'response_code':4002}
            identity={'email':email,'customer_id':body['customer_id'],'customer_ids':[body['customer_id']], 'member_token':'synthetic-member-session-token','token_expires_at':'2026-10-23 12:30:00'}
            self.members[email]={'password':'synthetic-temporary-secret','identity':identity}
            result={'response_code':100,'temp_password':'synthetic-temporary-secret'}
        elif name=='member_update':
            if saved['password']!=body['current_member_password']:return {'response_code':4008}
            saved['password']=body['new_member_password'];result={'response_code':100}
        elif name=='member_login':return {'response_code':100,'data':saved['identity']} if saved and saved['password']==body['member_password'] else {'response_code':4008}
        elif name=='member_check_session':return {'response_code':100 if self.active else 4007}
        elif name=='member_logout':self.active=False;return {'response_code':100}
        else:raise AssertionError(name)
        if self.fail_after==name:self.fail_after=None;raise TimeoutError('synthetic response loss')
        return result
    def count(self,name):return sum(n==name for n,_ in self.calls)

class StickyMembershipTests(unittest.TestCase):
    def setUp(self):
        member.MemberPortalTests.setUp(self)
        self.env=patch.dict(os.environ,{'MEMBER_IDENTITY_PROVIDER':'sticky'});self.env.start()
        self.remote=MembershipFake(self.app.state.admin.api.call);self.app.state.admin.api.call=self.remote
    def tearDown(self):self.env.stop();member.MemberPortalTests.tearDown(self)
    def receipt(self):return self.app.state.store.read(self.attempt)
    def setup(self):return self.service.receipt_account(self.receipt(),member.PATIENT_PASSWORD)
    def email(self):return next(iter(self.remote.members))
    def test_password_owned_by_sticky_no_email_or_local_hash(self):
        self.assertEqual(self.service.receipt_account(self.receipt())['state'],'set_password')
        self.assertEqual(self.setup()['state'],'ready')
        self.assertTrue(all('event_id' not in b for _,b in self.remote.calls))
        with self.service.db() as db:
            row=db.execute('SELECT * FROM member_patients').fetchone()
            self.assertEqual(row['password_hash'],'');self.assertEqual(row['salt'],'')
            bootstrap=db.execute('SELECT * FROM member_identity_bootstrap').fetchone()
            self.assertEqual(bootstrap['state'],'ready');self.assertIsNone(bootstrap['secret'])
            self.assertNotIn('synthetic-member-session-token',db.execute('SELECT secret FROM member_identity_sessions').fetchone()[0])
        login=self.client.post(self.base+'/auth/login',json={'email':self.email(),'password':member.PATIENT_PASSWORD})
        self.assertEqual(login.status_code,200,login.text)
        headers={'Authorization':'Bearer '+login.json()['access_token']}
        self.assertEqual(self.client.get(self.base+'/me',headers=headers).status_code,200)
        self.assertEqual(self.client.get('/api/v1/sites/site-b/portal/me',headers=headers).status_code,401)
        self.assertEqual(self.client.post(self.base+'/auth/logout',headers=headers).status_code,200)
        self.assertEqual(self.remote.count('member_logout'),1)
        self.assertEqual(self.client.get(self.base+'/me',headers=headers).status_code,401)
    def test_existing_password_never_reset_and_rate_limit(self):
        self.setup()
        for _ in range(10):
            with self.assertRaises(HTTPException) as caught:self.service.receipt_account(self.receipt(),'some-other-password')
            self.assertEqual(caught.exception.status_code,401)
        with self.assertRaises(HTTPException) as caught:self.setup()
        self.assertEqual(caught.exception.status_code,429)
        self.assertEqual(self.remote.count('member_create'),1);self.assertEqual(self.remote.count('member_update'),1)
    def test_create_uncertainty_no_retry(self):
        self.remote.fail_after='member_create'
        with self.assertRaises(HTTPException):self.setup()
        self.assertEqual(self.service.receipt_account(self.receipt())['state'],'needs_review')
        with self.assertRaises(HTTPException):self.setup()
        self.assertEqual(self.remote.count('member_create'),1);self.assertEqual(self.remote.count('member_update'),0)
    def test_update_response_lost_read_recovery_without_rewrite(self):
        self.remote.fail_after='member_update'
        with self.assertRaises(HTTPException):self.setup()
        with self.service.db() as db:self.assertNotIn('synthetic-temporary-secret',db.execute('SELECT secret FROM member_identity_bootstrap').fetchone()[0])
        del self.service._sticky_identity
        self.assertEqual(self.setup()['state'],'ready')
        self.assertEqual(self.remote.count('member_update'),1)
    def test_unpaid_or_unscoped_rejected(self):
        for changed in ({'status':'awaiting_card'},{'link_id':'missing'},{'order_id':'12345'}):
            with self.assertRaises(HTTPException):self.service.receipt_account(self.receipt()|changed,member.PATIENT_PASSWORD)
        self.assertEqual(self.remote.count('member_create'),0)
    def test_existing_patient_id_preserved_and_old_login_disabled(self):
        with patch.dict(os.environ,{'MEMBER_IDENTITY_PROVIDER':'local'}):
            order,_=self.service.receipt_order(self.receipt());existing=self.service.enroll('site-a',order,'previous-local-password','test')
        self.setup()
        with self.service.db() as db:
            row=db.execute('SELECT * FROM member_patients').fetchone()
            self.assertEqual(row['id'],existing['patient']['id']);self.assertEqual(row['password_hash'],'')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM member_patients').fetchone()[0],1)
        self.assertEqual(self.client.post(self.base+'/auth/login',json={'email':self.email(),'password':'previous-local-password'}).status_code,401)
        self.assertEqual(self.client.get(self.base+'/me',headers={'Authorization':'Bearer '+existing['access_token']}).status_code,401)
    def test_sticky_revocation_invalidates_session(self):
        self.setup();login=self.client.post(self.base+'/auth/login',json={'email':self.email(),'password':member.PATIENT_PASSWORD}).json()
        self.remote.active=False;self.service.clock=lambda:member.NOW+31
        self.assertEqual(self.client.get(self.base+'/me',headers={'Authorization':'Bearer '+login['access_token']}).status_code,401)
    def test_replay_reuses_member(self):
        self.setup();self.setup()
        self.assertEqual(self.remote.count('member_create'),1);self.assertEqual(self.remote.count('member_update'),1)
        with self.service.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM member_grants').fetchone()[0],1)

    def test_password_spaces_preserved_and_other_site_not_auto_granted(self):
        from member_portal.app import ReceiptEnrollment
        password='  Synthetic-special-pass!  '
        body=ReceiptEnrollment(password=password)
        self.assertEqual(body.password,password)
        self.service.receipt_account(self.receipt(),body.password)
        self.assertEqual(self.remote.members[self.email()]['password'],password)
        self.assertEqual(self.client.post('/api/v1/sites/site-b/portal/auth/login',json={'email':self.email(),'password':password}).status_code,401)
