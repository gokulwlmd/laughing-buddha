import copy
import unittest
from fastapi.testclient import TestClient
import test_admin


class RefillPolicyTests(unittest.TestCase):
    def setUp(self):
        test_admin.AdminTests.setUp(self)
        self.admin=self.app.state.admin
        self.master={'sku':'SEMA-12M','name':'Semaglutide','offers':[{'price':'999.00'}],'revision':4}
        self.admin.put('master','SEMA-12M',self.master)
    def tearDown(self):
        test_admin.AdminTests.tearDown(self)
    def save(self, **changes):
        body={'expected_revision':0,'enabled':True,'minimum_days':30,'request_window_days':14,'check_in_required':True,'review_required':True,'test_requests_enabled':False}|changes
        return self.client.put('/api/admin/master-refill-rules/SEMA-12M',headers=self.headers,json=body)
    def test_rules_disabled_by_default_and_separate_from_billing(self):
        result=self.client.get('/api/admin/master-refill-rules/SEMA-12M').json()
        self.assertFalse(result['enabled']);self.assertEqual(result['revision'],0)
        self.assertEqual(self.save().status_code,200)
        self.assertEqual(self.admin.get('master','SEMA-12M'),self.master)
        self.assertIsNone(self.admin.get('refill_policy','SEMA-6M'))
        self.assertEqual(self.admin.get('refill_policy','SEMA-12M')['revision'],1)
        self.assertEqual(self.fake.calls,[])
    def test_review_cannot_be_removed_and_conflicts_preserve_policy(self):
        self.assertEqual(self.save(review_required=False).status_code,422)
        self.assertEqual(self.save().status_code,200)
        self.assertEqual(self.save(enabled=False).status_code,409)
        self.assertTrue(self.admin.get('refill_policy','SEMA-12M')['enabled'])
        self.assertEqual(self.save(expected_revision=1,enabled=False).status_code,200)
    def test_owner_and_csrf_required_and_arbitrary_sku_rejected(self):
        outsider=TestClient(self.app,base_url=test_admin.ORIGIN)
        self.assertEqual(outsider.get('/api/admin/master-refill-rules/SEMA-12M').status_code,401)
        self.assertEqual(self.client.put('/api/admin/master-refill-rules/SEMA-12M',json={'expected_revision':0}).status_code,403)
        self.assertEqual(self.client.get('/api/admin/master-refill-rules/UNKNOWN').status_code,404)

    def test_product_intake_and_independent_check_in_schedule_saved(self):
        result=self.save(intake_template_id='weight-loss',check_in_days=[90,180,270])
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json()['check_in_days'],[90,180,270])
        self.assertTrue(result.json()['initial_intake_required'])
        self.assertEqual(self.admin.get('master','SEMA-12M'),self.master)
        self.assertEqual(self.fake.calls,[])

    def test_wrong_product_or_invalid_check_in_days_rejected(self):
        self.assertEqual(self.save(intake_template_id='metformin').status_code,422)
        self.assertEqual(self.save(check_in_days=[90]).status_code,422)
        for days in ([90,90],[180,90],[0],[731],[True],['90'],[90.5]):
            with self.subTest(days=days):
                self.assertEqual(self.save(intake_template_id='weight-loss',check_in_days=days).status_code,422)
        self.assertIsNone(self.admin.get('refill_policy','SEMA-12M'))

    def test_older_saved_policy_gets_new_defaults_without_rewrite(self):
        old={'sku':'SEMA-12M','revision':7,'enabled':True,'minimum_days':14}
        self.admin.put('refill_policy','SEMA-12M',old)
        result=self.client.get('/api/admin/master-refill-rules/SEMA-12M').json()
        self.assertEqual(result['revision'],7)
        self.assertEqual(result['intake_template_id'],'')
        self.assertEqual(result['check_in_days'],[])
        self.assertEqual(self.admin.get('refill_policy','SEMA-12M'),old)

    def test_included_claims_require_initial_and_post_claim_checkins(self):
        self.assertEqual(self.save(included_refills_enabled=True).status_code,422)
        for changes in ({'initial_intake_required':False},{'check_in_required':False},{'claim_window_days':0}):
            self.assertEqual(self.save(included_refills_enabled=True,intake_template_id='weight-loss',check_in_days=[90,180,270],**changes).status_code,422)
        result=self.save(included_refills_enabled=True,intake_template_id='weight-loss',check_in_days=[90,180,270],claim_window_days=10)
        self.assertEqual(result.status_code,200)
        self.assertEqual(self.admin.get('master','SEMA-12M'),self.master)
