"""Offline identity contract and ownership checks. No live identity requests."""
import json
import os
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from member_portal.wlmd import IdentityInput, WLMDClient
import test_member_portal as fixtures


class FakeIdentity:
    def __init__(self): self.calls = 0; self.result = True
    def available(self): return True
    def verify(self, site, order, last4):
        self.calls += 1
        assert site == 'qa-wlmd' and order == '9001' and len(last4) == 4
        return self.result


class IdentityTests(unittest.TestCase):
    setUp = fixtures.MemberPortalTests.setUp
    tearDown = fixtures.MemberPortalTests.tearDown
    post_owner = fixtures.MemberPortalTests.post_owner
    enroll = fixtures.MemberPortalTests.enroll

    def configure(self, enroll=True):
        if enroll: self.enroll()
        raw = self.service.admin.get('site', 'site-a')
        raw['wlmd_site_id'] = 'qa-wlmd'
        self.service.admin.put('site', 'site-a', raw)
        self.checks = self.service.identity_checks
        self.provider = FakeIdentity(); self.checks.provider = self.provider
        self.path = self.base + '/orders/9001/identity'

    def verify(self, value='1234'):
        return self.client.post(self.path, json={'last4': value}, headers=self.patient_headers)

    def test_intake_is_gated_then_reuses_verification_without_storing_digits(self):
        self.configure()
        for method, suffix, body in [('GET','',None),('PATCH','',{'revision':0,'answers':{}}),('POST','/submit',{'revision':0})]:
            response=self.client.request(method,self.base+'/intakes/9001'+suffix,json=body,headers=self.patient_headers)
            self.assertEqual(response.status_code,409 if method=='POST' else 200,response.text)
            if method=='POST':self.assertEqual(response.json()['detail']['code'],'identity_verification_required')
        self.assertEqual(self.provider.calls,0)
        self.assertEqual(self.verify().status_code,200)
        self.assertEqual(self.verify().json()['status'],'verified')
        self.assertEqual(self.provider.calls,1)
        self.assertEqual(self.client.get(self.base+'/intakes/9001',headers=self.patient_headers).status_code,200)
        status=self.client.get(self.base+'/account/identity',headers=self.patient_headers).json()
        self.assertEqual(status['status'],'verified');self.assertTrue(status['verified_at'])
        with self.service.db() as db:
            saved=json.dumps([dict(r) for r in db.execute('SELECT * FROM member_identity_checks')])
        self.assertNotIn('1234',saved);self.assertNotIn('last4',saved)

    def test_ownership_authentication_validation_and_mapping_changes(self):
        self.configure()
        self.assertEqual(self.client.post(self.path,json={'last4':'1234'}).status_code,401)
        self.assertEqual(self.client.post(self.path.replace('9001','9999'),json={'last4':'1234'},headers=self.patient_headers).status_code,404)
        for invalid in ['123','12345','１２３４','12a4']:
            response=self.verify(invalid)
            self.assertEqual(response.status_code,422);self.assertNotIn(invalid,response.text)
        self.assertEqual(self.provider.calls,0)
        self.assertEqual(self.verify().status_code,200)
        raw=self.service.admin.get('site','site-a');raw['wlmd_site_id']='changed';self.service.admin.put('site','site-a',raw)
        self.assertEqual(self.client.get(self.path,headers=self.patient_headers).json()['status'],'needed')
        self.assertNotEqual(self.client.get(self.path.replace('site-a','site-b'),headers=self.patient_headers).status_code,200)

    def test_failure_never_verifies_and_explicit_retries_are_limited(self):
        self.configure();self.provider.result=False
        self.assertEqual(self.verify().status_code,409)
        self.assertEqual(self.verify().status_code,429)
        for _ in range(3): self.client.get(self.path,headers=self.patient_headers)
        self.assertEqual(self.provider.calls,1)
        self.assertEqual(self.client.get(self.path,headers=self.patient_headers).json()['status'],'needed')
        now=self.service.clock();self.service.clock=lambda: now + 31
        self.provider.result=True
        self.assertEqual(self.verify().status_code,200)

    def test_guest_result_is_adopted_but_guest_cannot_read_other_account_checks(self):
        self.configure(enroll=False)
        order,guest=self.service.receipt_order(self.app.state.store.read(self.attempt))
        self.checks.verify(order,guest,IdentityInput(last4='1234'))
        self.enroll()
        status=self.client.get(self.base+'/account/identity',headers=self.patient_headers).json()
        self.assertEqual(status['status'],'verified')
        self.assertEqual(self.checks.status(order,guest)['status'],'verified')
        other=dict(order);other['order_id']='9002'
        self.assertEqual(self.checks.status(other,{'id':'receipt:9002','_reuse_allowed':False})['status'],'needed')
        with self.service.db() as db:
            patient_id=db.execute("SELECT patient_id FROM member_grants WHERE order_id='9001'").fetchone()[0]
        self.assertEqual(self.checks.status(other,{'id':patient_id})['status'],'verified')
        self.assertEqual(self.provider.calls,1)

    def test_unavailable_is_not_silently_skipped_and_unmapped_is_unchanged(self):
        self.configure();self.provider.available=lambda:False
        self.assertEqual(self.verify().status_code,503)
        self.assertEqual(self.provider.calls,0)
        raw=self.service.admin.get('site','site-a');raw.pop('wlmd_site_id');self.service.admin.put('site','site-a',raw)
        self.assertEqual(self.client.get(self.base+'/intakes/9001',headers=self.patient_headers).status_code,200)

    def test_receipt_can_reuse_only_its_own_trusted_ssn_question(self):
        self.configure(enroll=False)
        order,guest=self.service.receipt_order(self.app.state.store.read(self.attempt))
        self.checks.verify(order,guest,IdentityInput(last4='1234'))
        template={'version':'future-1','sections':[], 'questions':[{'id':'ssn_check','type':'text','label':'Identity','reuse_key':'identity.ssn_verified','reuse_policy':'verified'}]}
        with self.service.db() as db:
            seeded,answers=self.service.answer_profile.seed(db,order,guest,template)
            self.assertEqual(answers,{'ssn_check':'verified'})
            self.service.answer_profile.validate(db,order,guest,seeded,submit=True,answers=answers)
            other=dict(order);other['order_id']='9002'
            _,other_answers=self.service.answer_profile.seed(db,other,{'id':'receipt:9002','_reuse_allowed':False},template)
            self.assertEqual(other_answers,{})

    def test_care_checkin_gate_and_trusted_ssn_fact(self):
        self.configure()
        order=self.service.order_record('site-a','9001')
        with self.service.db() as db:
            patient={'id':db.execute("SELECT patient_id FROM member_grants WHERE order_id='9001'").fetchone()[0]}
        from patient_demo.app import IntakeSubmit
        with self.assertRaises(HTTPException) as caught: self.service.care.modify(order,patient,'initial',IntakeSubmit(revision=0),True)
        self.assertEqual(caught.exception.detail['code'],'identity_verification_required')
        self.verify()
        with self.service.db() as db:
            self.assertTrue(self.checks.fact(db,order,patient,'identity.ssn_verified','1'))
            self.assertIsNone(self.checks.fact(db,order,patient,'identity.id_verified','1'))


class ClientTests(unittest.TestCase):
    def test_exact_success_only_and_no_redirect_or_raw_errors(self):
        class Response:
            status=200
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,limit): return self.body
        response=Response()
        with patch.dict(os.environ,{'WLMD_API_URL':'https://api.whitelabelmd.com','WLMD_AUTHTOKEN':'qa-key=qa-secret'}):
            with patch('member_portal.wlmd.request.build_opener') as factory:
                factory.return_value.open.return_value=response
                for body,expected in [(b'{"status":"success"}',True),(b'{"status":"pending"}',False),(b'{"status":true}',False),(b'<html>error</html>',False),(b'[]',False)]:
                    response.body=body
                    self.assertEqual(WLMDClient().verify('qa-site','9001','1234'),expected)
                req=factory.return_value.open.call_args.args[0]
                self.assertEqual(json.loads(req.data),{'user':'laughing-buddha','last4':'1234'})
                self.assertEqual(req.full_url,'https://api.whitelabelmd.com/v1/site/qa-site/order/9001/identity_ssncheck')
                factory.return_value.open.side_effect=TimeoutError('PRIVATE PROVIDER BODY')
                self.assertFalse(WLMDClient().verify('qa-site','9001','1234'))
        self.assertNotIn('1234',repr(IdentityInput(last4='1234')))
