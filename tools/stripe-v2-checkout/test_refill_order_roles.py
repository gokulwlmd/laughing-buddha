"""Same-SKU care routing through application APIs with an offline provider."""
import json
import test_member_renewals as renewals
from member_portal.order_roles import order_role

class RefillOrderRoleTests(renewals.RenewalTests):
    def test_paid_renewal_uses_checkin_and_keeps_original_sku(self):
        result = self.confirm(self.preview())
        self.assertEqual(result.status_code, 200, result.text)
        orders = self.client.get(self.base+'/orders', headers=self.patient_headers).json()['orders']
        child = next(o for o in orders if o['id']=='9002')
        self.assertEqual(child['sku'], 'SEMA-1M-SUB')
        self.assertEqual(child['order_role'], 'paid_renewal')
        self.assertEqual(child['intake_kind'], 'checkin')
        response = self.client.get(self.base+'/intakes/9002', headers=self.patient_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('-checkin-', response.json()['template']['id'])
        root = self.client.get(self.base+'/intakes/9001', headers=self.patient_headers)
        self.assertIn('-initial-', root.json()['template']['id'])

    def test_no_checkin_policy_skips_form_without_claiming_medical_approval(self):
        rule = self.app.state.admin.get('refill_policy', 'SEMA-1M-SUB'); rule['check_in_required'] = False
        self.app.state.admin.put('refill_policy', 'SEMA-1M-SUB', rule)
        self.assertEqual(self.confirm(self.preview()).status_code, 200)
        orders = self.client.get(self.base+'/orders', headers=self.patient_headers).json()['orders']
        child = next(o for o in orders if o['id']=='9002')
        self.assertEqual(child['intake_status'], 'not_required')
        self.assertEqual(child['intake_kind'], 'none')
        self.assertNotEqual(child['medical_status'], 'approved')
        self.assertEqual(self.client.get(self.base+'/intakes/9002', headers=self.patient_headers).status_code, 409)

    def test_lineage_rejects_other_site_product_or_subscription(self):
        self.assertEqual(self.confirm(self.preview()).status_code, 200)
        root = self.service.order_record('site-a', '9001'); child = self.service.order_record('site-a', '9002')
        for field in ('site_id','customer_id','sku'):
            other = dict(child); other[field] = 'unrelated'
            self.assertEqual(order_role(other, root), 'unconfirmed')
        for field in ('product_id','sku','subscription_id'):
            other = dict(child); raw = json.loads(other['payload']); raw['products'][0][field] = 'unrelated'; other['payload'] = json.dumps(raw)
            self.assertEqual(order_role(other, root), 'unconfirmed')
        self.assertEqual(order_role(child), 'unconfirmed')
        self.assertEqual(order_role(root), 'initial')

for name in vars(renewals.RenewalTests):
    if name.startswith('test_') and name not in vars(RefillOrderRoleTests): setattr(RefillOrderRoleTests, name, None)


import test_member_native_claims as native

class IncludedOrderRoutingTests(native.NativeClaimTests):
    def test_child_intake_api_edits_its_checkin_not_original_answers(self):
        original = self.complete('initial')
        self.simulate(80)
        result = self.claim()
        self.assertEqual(result.status_code, 200, result.text)
        child = result.json()['claim']['order_id']
        path = self.base + '/intakes/' + child
        response = self.client.get(path, headers=self.patient_headers)
        self.assertEqual(response.status_code, 200, response.text)
        form = response.json()
        self.assertIn('-checkin-', form['template']['id'])
        self.assertNotEqual(form['id'], original['id'])
        patched = self.client.patch(path, headers=self.patient_headers, json={'revision':form['revision'], 'answers':{}})
        self.assertEqual(patched.status_code, 200, patched.text)
        self.assertEqual(patched.json()['id'], form['id'])
        root = self.client.get(self.base+'/intakes/9001', headers=self.patient_headers).json()
        self.assertEqual(root['answers'], original['answers'])
        self.assertEqual(root['status'], 'submitted')

for parent in IncludedOrderRoutingTests.__mro__[1:]:
    for name in vars(parent):
        if name.startswith('test_') and name not in vars(IncludedOrderRoutingTests): setattr(IncludedOrderRoutingTests, name, None)
