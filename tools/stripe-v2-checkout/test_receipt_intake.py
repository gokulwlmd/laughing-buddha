"""Receipt capabilities save intake before account creation."""
import json
import unittest
from fastapi import HTTPException
from patient_demo.app import IntakePatch, IntakeSubmit
from patient_demo.provider import get_sample_answers
import test_member_portal as member

class ReceiptIntakeTests(unittest.TestCase):
    setUp = member.MemberPortalTests.setUp
    tearDown = member.MemberPortalTests.tearDown
    post_owner = member.MemberPortalTests.post_owner
    enroll = member.MemberPortalTests.enroll

    def receipt(self):
        return self.service.receipt_order(self.app.state.store.read(self.attempt))

    def test_guest_draft_survives_enrollment(self):
        order, guest = self.receipt()
        initial = self.service.initial_intake(order, guest)
        self.assertEqual(initial['template']['sku'], 'SEMA-1M-SUB')
        self.service.modify_initial(order, IntakePatch(revision=0, answers={'allergies':'Synthetic answer'}, current_step=1), guest)
        with self.service.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM member_patients').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM member_grants').fetchone()[0],0)
        self.enroll()
        actual=self.client.get(self.base+'/intakes/9001',headers=self.patient_headers)
        self.assertEqual(actual.status_code,200,actual.text)
        self.assertEqual(actual.json()['answers']['allergies'],'Synthetic answer')
        self.assertEqual(actual.json()['current_step'],1)
        self.assertEqual(self.client.get('/api/v1/sites/site-b/portal/intakes/9001',headers=self.patient_headers).status_code,401)

    def test_submit_revision_and_required_answers(self):
        order,guest=self.receipt();self.service.initial_intake(order,guest)
        with self.assertRaises(HTTPException) as error:self.service.modify_initial(order,IntakeSubmit(revision=0),guest,True)
        self.assertEqual(error.exception.status_code,422)
        answers=get_sample_answers('weight-loss');answers.pop('demo_confirmation')
        self.service.modify_initial(order,IntakePatch(revision=0,answers=answers),guest)
        with self.assertRaises(HTTPException) as conflict:self.service.modify_initial(order,IntakePatch(revision=0,answers={}),guest)
        self.assertEqual(conflict.exception.status_code,409)
        self.assertEqual(self.service.modify_initial(order,IntakeSubmit(revision=1),guest,True)['status'],'submitted')
        self.enroll()
        self.assertEqual(self.client.get(self.base+'/intakes/9001',headers=self.patient_headers).json()['status'],'submitted')

    def test_rejects_unpaid_and_mismatched_receipts(self):
        row=self.app.state.store.read(self.attempt)
        for changed in ({'status':'awaiting_card'},{'link_id':'unknown'},{'order_id':'9999'}):
            with self.assertRaises(HTTPException):self.service.receipt_order(row|changed)

    def test_initial_intake_independent_of_shipping_schedule(self):
        order,guest=self.receipt()
        from refill_rules import site_rule_key
        self.app.state.admin.put('site_refill_policy',site_rule_key('site-a','SEMA-1M-SUB'),{'site_id':'site-a','sku':'SEMA-1M-SUB','enabled':True,'intake_template_id':'weight-loss','initial_intake_required':True,'check_in_days':[]})
        snapshot=json.loads(order['snapshot']);snapshot['schedule_verified']=False
        with self.service.db() as db:db.execute('UPDATE member_orders SET snapshot=? WHERE order_id=?',(json.dumps(snapshot),order['order_id']))
        order,guest=self.receipt()
        self.assertEqual(self.service.initial_intake(order,guest)['status'],'draft')
        self.enroll()
        self.assertEqual(self.client.get(self.base+'/intakes/9001',headers=self.patient_headers).status_code,200)
        self.assertEqual(self.client.get(self.base+'/orders/9001/care-tasks/initial/intake',headers=self.patient_headers).status_code,200)

    def test_single_shipment_has_no_refill_checkpoint(self):
        self.enroll()
        from refill_rules import site_rule_key
        self.app.state.admin.put('site_refill_policy',site_rule_key('site-a','SEMA-1M-SUB'),{'site_id':'site-a','sku':'SEMA-1M-SUB','enabled':True,'intake_template_id':'weight-loss','initial_intake_required':True,'check_in_days':[]})
        order=self.service.order_record('site-a','9001');snapshot=json.loads(order['snapshot']);snapshot['product_setup']={'shipment_count':1,'term_months':1,'shipment_interval_days':30}
        with self.service.db() as db:db.execute('UPDATE member_orders SET snapshot=? WHERE order_id=?',(json.dumps(snapshot),order['order_id']))
        order=self.service.order_record('site-a','9001');plan=self.service.care.ensure(order)
        self.assertIsNotNone(plan)
        self.assertFalse(self.service.care.raw_tasks(order,plan)[0]['refill_checkpoint'])
        self.assertFalse(self.service.care.availability(order)['eligible'])
        self.assertIn('one delivery',self.service.care.availability(order)['reason'])
