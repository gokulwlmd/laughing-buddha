import unittest
from member_portal.journey import order_journey
from test_receipt_intake import ReceiptIntakeTests
from patient_demo.app import IntakePatch


class JourneyEvidenceTests(unittest.TestCase):
    def order(self, **changes):
        return dict(payment_status='paid', intake_status='not_started', medical_status='not_connected',
                    fulfillment_status='unknown', **changes)

    def test_unconnected_review_is_not_claimed_as_started(self):
        order=self.order();order['intake_status']='submitted'
        journey=order_journey(order)
        self.assertEqual(journey['next_action'], 'wait')
        self.assertEqual(journey['title'], 'Your intake is saved')
        self.assertEqual(journey['stages'][2]['state'], 'unconfirmed')
        self.assertNotIn('Awaiting review', str(journey))

    def test_shipment_does_not_complete_unrecorded_clinical_steps(self):
        order=self.order();order.update(fulfillment_status='shipped',tracking_number='QA-TRACKING',shipping_date='2026-10-25')
        journey=order_journey(order)
        self.assertEqual(journey['next_action'],'shipment')
        self.assertEqual(journey['stages'][4]['state'],'complete')
        self.assertEqual(journey['stages'][2]['state'],'unconfirmed')
        self.assertEqual(journey['tracking_number'],'QA-TRACKING')
        self.assertFalse(any(s['state']=='current' for s in journey['stages']))

    def test_draft_and_payment_problem_have_distinct_actions(self):
        order=self.order();order['intake_status']='draft'
        self.assertEqual(order_journey(order)['title'],'Continue your health intake')
        order['payment_status']='refunded'
        journey=order_journey(order)
        self.assertEqual(journey['next_action'],'support')
        self.assertFalse(any(s['state']=='current' for s in journey['stages']))


class ReceiptJourneyTests(ReceiptIntakeTests):
    def test_journey_discloses_only_owned_order_progress(self):
        receipt=self.app.state.store.read(self.attempt)
        value=self.service.receipt_journey(receipt)
        self.assertEqual(value['id'],'9001')
        self.assertEqual(set(value), {'id','product_name','intake_status','journey'})
        self.assertNotIn('customer',str(value))
        self.assertNotIn('email',str(value))
        order,guest=self.receipt()
        self.service.modify_initial(order,IntakePatch(revision=0,answers={'allergies':'Private fixture answer'}),guest)
        self.assertNotIn('Private fixture answer',str(self.service.receipt_journey(receipt)))
        self.enroll()
        result=self.client.get(self.base+'/orders',headers=self.patient_headers)
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json()['orders'][0]['journey']['next_action'],'intake')
