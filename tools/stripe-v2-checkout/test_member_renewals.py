"""Native early renewal, pricing and replay protection; all provider calls offline."""
from copy import deepcopy
from datetime import datetime, timezone
import unittest
import test_member_portal as fixtures
from test_member_provider import FakeSticky
from member_portal.provider import ProviderError


class RenewalSticky(FakeSticky):
    def __init__(self):
        super().__init__()
        self.order['products'][0].update(billing_model={'id':3},offer={'id':7002},is_in_trial='0')
        self.subscription.update(is_recurring=True,recur_at='2026-11-22',credit='0.00',stop_after_next_rebill=False,
            product={'id':7001,'quantity':1,'children':[]},next_product={'id':7001,'quantity':1,'children':[]},
            billing_model={'id':3,'type':{'id':1},'days':30,'expire_cycles':0,'buffer_days':0,'is_archived':0})
        self.total='2.99';self.children={};self.uncertain=False;self.bad_date=False;self.fail_date=False

    def call(self, method, path, body=None):
        if path=='/api/v2/providers/payment/profiles/254':
            return {'status':'SUCCESS','data':{'id':254,'account_id':250,'currency':{'code':'USD'}}}
        if path=='/api/v2/recurring_total/calculate':
            self.calls.append((method,path,deepcopy(body)))
            return {'status':'SUCCESS','data':{'2026-11-22':{'total':self.total,'shipping':{'shipping_total_amount':0,'shipping_tax_amount':0},'tax':{'sales_tax_amount':0,'vat_tax_amount':0},
                'line_items':{'synthetic-subscription-1':{'product_id':7001,'qty':1,'subscription_id':'synthetic-subscription-1','is_bundle':False,'is_variant':False,'is_taxable':0,'total':self.total}}}}}
        if path=='/api/v1/order_force_bill':
            self.calls.append((method,path,deepcopy(body)))
            child=deepcopy(self.order);child.update(order_id='9002',parent_id='9001',ancestor_id='9001',child_id='',order_total=self.total,time_stamp='2026-10-23 12:00:00')
            child['products'][0]['recurring_date']='2026-12-22' if self.bad_date else '2026-11-22'
            self.subscription['recur_at']=child['products'][0]['recurring_date']
            self.children['9002']=child;self.order['child_id']='9002'
            if self.uncertain:raise TimeoutError('Private upstream response')
            return {'response_code':'100','error_found':'0','new_order_id':'9002'}
        if path=='/api/v1/subscription_order_update' and 'new_recurring_date' in (body or {}):
            self.calls.append((method,path,deepcopy(body)))
            if self.fail_date:raise TimeoutError('Private upstream response')
            date=datetime.strptime(body['new_recurring_date'],'%m/%d/%Y').date().isoformat()
            self.children[body['order_id']]['products'][0]['recurring_date']=date;self.subscription['recur_at']=date
            return {'response_code':'100'}
        if path=='/api/v1/order_view' and str(body['order_id'][0]) in self.children:
            self.calls.append((method,path,deepcopy(body)));return deepcopy(self.children[str(body['order_id'][0])])
        return super().call(method,path,body)


class RenewalTests(unittest.TestCase):
    setUpBase=fixtures.MemberPortalTests.setUp
    tearDown=fixtures.MemberPortalTests.tearDown
    enroll=fixtures.MemberPortalTests.enroll
    post_owner=fixtures.MemberPortalTests.post_owner

    def setUp(self):
        self.setUpBase();self.fake=RenewalSticky();self.service.provider.api=self.fake
        self.app.state.admin.put('refill_policy','SEMA-1M-SUB',{'enabled':True,'allow_paid_early_renewal':True,'initial_intake_required':False,'minimum_days':0,'early_request_minimum_days':0})
        self.enroll();self.path=self.base+'/orders/9001/subscriptions/synthetic-subscription-1/renewal'

    def preview(self):
        r=self.client.get(self.path,headers=self.patient_headers);self.assertEqual(r.status_code,200,r.text);return r.json()

    def confirm(self,quote,**kwargs):
        return self.client.post(self.path,headers=self.patient_headers,json={'quote_id':quote['quote_id'],'confirmed':True,**kwargs})

    def writes(self):
        return [x for x in self.fake.calls if x[1]=='/api/v1/order_force_bill']

    def test_verified_discounted_quote_and_single_native_renewal(self):
        q=self.preview();self.assertTrue(q['available'],q);self.assertEqual(q['amount'],'2.99');self.assertFalse(self.writes())
        r=self.confirm(q);self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['order_id'],'9002')
        self.assertEqual(self.confirm(q).status_code,200);self.assertEqual(len(self.writes()),1)
        self.assertEqual(self.writes()[0][2],{'order_id':'9001','product_id':'7001','forceGatewayId':254,'preserve_force_gateway':1})
        orders=self.client.get(self.base+'/orders',headers=self.patient_headers).json()['orders'];self.assertEqual({o['id'] for o in orders},{'9001','9002'})
        self.assertFalse(any(p in ('/api/v1/new_order','/api/v1/authorize_payment') for _,p,_ in self.fake.calls))

    def test_price_change_and_expiration_require_new_confirmation(self):
        q=self.preview();self.fake.total='299.00';self.assertEqual(self.confirm(q).status_code,409);self.assertFalse(self.writes())
        self.fake.total='2.99';self.service.clock=lambda:datetime(2026,10,23,12,10,tzinfo=timezone.utc).timestamp()
        self.assertEqual(self.confirm(q).status_code,409);self.assertFalse(self.writes())

    def test_uncertain_payment_adopts_child_by_read_only_reconciliation(self):
        q=self.preview();self.fake.uncertain=True
        r=self.confirm(q);self.assertEqual(r.status_code,409,r.text);self.assertNotIn('Private',r.text)
        r=self.confirm(q);self.assertEqual(r.status_code,200,r.text);self.assertEqual(len(self.writes()),1)

    def test_date_repair_is_verified_and_failed_repair_never_recharges(self):
        q=self.preview();self.fake.bad_date=True;self.fake.fail_date=True
        self.assertEqual(self.confirm(q).status_code,409);self.assertEqual(self.confirm(q).status_code,409);self.assertEqual(len(self.writes()),1)
        self.fake.children['9002']['products'][0]['recurring_date']=q['next_billing_date'];self.fake.subscription['recur_at']=q['next_billing_date']
        self.assertEqual(self.confirm(q).status_code,200);self.assertEqual(len(self.writes()),1)

    def test_corrects_next_date_on_same_child_not_new_subscription(self):
        q=self.preview();self.fake.bad_date=True
        r=self.confirm(q);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.fake.children['9002']['products'][0]['recurring_date'],q['next_billing_date'])
        self.assertEqual(len(self.writes()),1)

    def test_two_previews_cannot_charge_same_source_twice(self):
        one,two=self.preview(),self.preview();self.assertEqual(self.confirm(one).status_code,200)
        self.assertEqual(self.confirm(two).status_code,409);self.assertEqual(len(self.writes()),1)

    def test_site_ownership_policy_and_consent_boundaries(self):
        q=self.preview()
        self.assertEqual(self.client.get(self.path.replace('site-a','site-b'),headers=self.patient_headers).status_code,401)
        self.assertEqual(self.confirm(q,confirmed=False).status_code,409)
        self.assertEqual(self.confirm(q,amount='0.01').status_code,422)
        self.app.state.admin.put('refill_policy','SEMA-1M-SUB',{'enabled':False})
        self.assertFalse(self.preview()['available']);self.assertEqual(self.confirm(q).status_code,409);self.assertFalse(self.writes())

    def test_intake_required_before_payment_but_amount_still_visible(self):
        rule=self.app.state.admin.get('refill_policy','SEMA-1M-SUB');rule['initial_intake_required']=True;self.app.state.admin.put('refill_policy','SEMA-1M-SUB',rule)
        q=self.preview();self.assertFalse(q['available']);self.assertEqual(q['amount'],'2.99');self.assertIn('health intake',q['reason']);self.assertFalse(self.writes())

    def test_completed_required_intake_allows_confirm_without_nested_writer(self):
        rule=self.app.state.admin.get('refill_policy','SEMA-1M-SUB');rule['initial_intake_required']=True;self.app.state.admin.put('refill_policy','SEMA-1M-SUB',rule)
        path=self.base+'/intakes/9001'
        self.assertEqual(self.client.get(path,headers=self.patient_headers).status_code,200)
        answers=fixtures.get_sample_answers('weight-loss');answers.pop('demo_confirmation')
        self.assertEqual(self.client.patch(path,headers=self.patient_headers,json={'revision':0,'answers':answers,'current_step':2}).status_code,200)
        self.assertEqual(self.client.post(path+'/submit',headers=self.patient_headers,json={'revision':1}).status_code,200)
        q=self.preview();self.assertTrue(q['available'],q)
        result=self.confirm(q);self.assertEqual(result.status_code,200,result.text);self.assertEqual(len(self.writes()),1)

    def test_due_schedule_or_changed_product_or_billing_model_blocked(self):
        for change in [lambda:self.fake.subscription.update(status='paused'),lambda:self.fake.subscription['next_product'].update(id=999),lambda:self.fake.subscription['billing_model'].update(type={'id':5})]:
            baseline=deepcopy(self.fake.subscription);change();self.assertFalse(self.preview()['available']);self.fake.subscription=baseline
        self.fake.order['products'][0]['recurring_date']='2026-10-24'
        self.assertFalse(self.preview()['available']);self.assertFalse(self.writes())

    def test_prepaid_and_trial_never_use_paid_renewal_path(self):
        self.fake.order['products'][0]['is_in_trial']='1'
        self.assertFalse(self.preview()['available']);self.assertFalse(self.writes())
        self.fake.order['products'][0]['is_in_trial']='0'
        self.fake.order['products'][0]['prepaid']=[{'current_cycle':'1','total_cycles':'4','is_renew':'1'}]
        self.assertFalse(self.preview()['available']);self.assertFalse(self.writes())

    def test_cross_action_pending_hold_blocks_charge(self):
        q=self.preview()
        with self.service.db() as db:db.execute('INSERT INTO member_actions VALUES(?,?,?,?,?,?,?,?,?)',('other','site-a','someone','9001','synthetic-subscription-1','pause','other','pending',self.service.clock()))
        self.assertEqual(self.confirm(q).status_code,409);self.assertFalse(self.writes())
