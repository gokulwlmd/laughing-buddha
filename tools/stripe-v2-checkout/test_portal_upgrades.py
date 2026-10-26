"""Replacement checkout boundaries. Offline provider only; no real orders."""
import json
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from fastapi import HTTPException
from test_member_portal import MemberPortalTests, NOW
from test_member_care import configure_care_fixture

class UpgradeTests(unittest.TestCase):
    setUpBase=MemberPortalTests.setUp
    tearDown=MemberPortalTests.tearDown
    enroll=MemberPortalTests.enroll
    post_owner=MemberPortalTests.post_owner

    def setUp(self):
        self.setUpBase()
        configure_care_fixture(self.app,self.fake,months=1)
        self.enroll()
        self.manager=self.service.upgrades
        self.row=self.service.order_record('site-a','9001')
        with self.service.db() as db:
            self.patient=dict(db.execute('SELECT * FROM member_patients').fetchone())
        self.path=self.base+'/orders/9001/upgrade'

    def policy(self): return self.manager.policy(self.service.order_record('site-a','9001'))

    def saved(self,sub='synthetic-subscription-1',status='open'):
        row={'id':'upgrade_test','site_id':'site-a','patient_id':self.patient['id'],'source_order_id':'9001','term_id':'9001','subscription_id':sub,'plan_id':'plan-test','sku':'TIRZ-1M-SUB','api_site':'example','session_id':'session-test','secret':'ciphertext','status':status,'new_order_id':None,'created':NOW}
        with self.service.db() as db: db.execute('INSERT INTO member_upgrades VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',tuple(row.values()))
        return row

    def test_window_exact_day10_for_30_days_and_remains_open(self):
        self.assertFalse(self.policy()['eligible'])
        self.service.clock=lambda:NOW+9*86400;self.assertFalse(self.policy()['eligible'])
        self.service.clock=lambda:NOW+10*86400;self.assertTrue(self.policy()['eligible'],self.policy())
        self.service.clock=lambda:NOW+35*86400;self.assertTrue(self.policy()['eligible'])

    def test_quarterly_twelve_month_requires_all_included_refills_and_day340(self):
        plan=self.service.care.ensure(self.row)
        data=json.loads(plan['snapshot']);data.update(coverage_days=360,product_setup={'shipment_count':4,'shipment_interval_days':90})
        with self.service.db() as db:db.execute('UPDATE member_care_plans SET snapshot=? WHERE id=?',(json.dumps(data),plan['id']))
        self.service.clock=lambda:NOW+340*86400
        with patch.object(self.service.care,'tasks',return_value=[{'refill_checkpoint':True,'claim':{'status':'claimed'}}]*2):
            self.assertFalse(self.policy()['eligible']);self.assertEqual(self.policy()['included_remaining'],1)
        with patch.object(self.service.care,'tasks',return_value=[{'refill_checkpoint':True,'claim':{'status':'claimed'}}]*3):
            self.service.clock=lambda:NOW+339*86400;self.assertFalse(self.policy()['eligible'])
            self.service.clock=lambda:NOW+340*86400;self.assertTrue(self.policy()['eligible'])

    def test_missing_schedule_and_foreign_site_fail_closed(self):
        with self.service.db() as db:
            snap=json.loads(self.row['snapshot']);snap['schedule_verified']=False
            db.execute('UPDATE member_orders SET snapshot=?',(json.dumps(snap),))
        self.assertFalse(self.policy()['eligible'])
        self.assertEqual(self.client.get(self.path.replace('site-a','site-b'),headers=self.patient_headers).status_code,401)
        self.assertEqual(self.client.get(self.path).status_code,401)

    def test_outside_window_no_checkout_or_provider_write(self):
        r=self.client.post(self.path,headers=self.patient_headers,json={'plan_id':'anything'})
        self.assertEqual(r.status_code,409,r.text)
        self.assertFalse(any(path in ('/api/v1/new_order','/api/v1/subscription_order_update') for _,path,_ in self.fake.calls))

    def capture(self,saved,subscription_failure=False):
        self.app.state.site_api_store=SimpleNamespace(read=lambda key:{'attempt':'attempt-new'})
        result=SimpleNamespace(status='captured',model_dump=lambda:{'status':'captured'})
        new=deepcopy(self.row);new.update(order_id='9999',sku=saved['sku'])
        raw=json.loads(new['payload']);raw['customer']['email']=self.patient['email'];new['payload']=json.dumps(raw)
        with patch.object(self.service.store,'read',return_value={'status':'captured','order_id':'9999'}),patch.object(self.service,'receipt_order',return_value=(new,{})),patch.object(self.manager,'latest',return_value=(self.row,self.row)),patch.object(self.manager,'policy',return_value={'eligible':True}),patch.object(self.service.provider,'subscription_action',side_effect=TimeoutError() if subscription_failure else None) as stop,patch.object(self.service,'sync',return_value=self.row):
            answer=self.manager.finish(self.app,saved,self.patient,result)
        return answer,stop.call_count

    def test_unpaid_never_stops_old_subscription(self):
        saved=self.saved()
        with patch.object(self.service.provider,'subscription_action') as stop:
            result=self.manager.finish(self.app,saved,self.patient,SimpleNamespace(status='awaiting_card',model_dump=lambda:{'status':'awaiting_card'}))
        self.assertEqual(result['status'],'awaiting_card');stop.assert_not_called()

    def test_capture_links_order_then_stops_once_and_replay_is_read_only(self):
        saved=self.saved();answer,count=self.capture(saved)
        self.assertTrue(answer['replacement_complete']);self.assertEqual(count,1)
        saved=self.manager.read('site-a',saved['id'],self.patient)
        answer,count=self.capture(saved);self.assertEqual(count,0)
        with self.service.db() as db:self.assertEqual(db.execute("SELECT patient_id FROM member_grants WHERE order_id='9999'").fetchone()[0],self.patient['id'])

    def test_one_time_checkout_never_calls_subscription_update(self):
        answer,count=self.capture(self.saved(sub=''));self.assertEqual(count,0);self.assertTrue(answer['replacement_complete'])

    def test_uncertain_stop_held_never_retried_and_blocks_renewal(self):
        saved=self.saved();answer,count=self.capture(saved,True)
        self.assertEqual(count,1);self.assertFalse(answer['replacement_complete'])
        self.assertEqual(self.manager.read('site-a',saved['id'],self.patient)['status'],'needs_review')
        self.assertTrue(self.manager.busy_subscription('site-a',saved['subscription_id']))
        self.assertIn('replacement',self.service.renewals.gate(self.row))
        response=self.client.get(self.base+'/upgrades/'+saved['id']+'/status',headers=self.patient_headers)
        self.assertEqual(response.json()['status'],'needs_review')

    def test_replaced_subscription_cannot_be_resumed(self):
        saved=self.saved(status='complete')
        r=self.client.post(self.base+'/orders/9001/subscriptions/'+saved['subscription_id']+'/resume',headers=self.patient_headers,json={'client_request_id':'test-resume-request'})
        self.assertEqual(r.status_code,409,r.text)

    def test_quote_cannot_switch_to_another_email(self):
        saved=self.saved()
        response=self.client.post(self.base+'/upgrades/'+saved['id']+'/quote',headers=self.patient_headers,json={'contact':{'email':'other@example.invalid'}})
        self.assertEqual(response.status_code,422)

    def test_replacement_requires_explicit_consent(self):
        saved=self.saved()
        response=self.client.post(self.base+'/upgrades/'+saved['id']+'/payment',headers=self.patient_headers,json={'quote_id':'x','accept_terms':False})
        self.assertEqual(response.status_code,422)

    def test_start_is_idempotent_private_and_exact_selection_bound(self):
        from demo.session_api import SessionCreated
        from unittest.mock import Mock
        selected={'plan_id':'portal-choice-test','sku':'TIRZ-1M-SUB','checkout_url':'https://example.invalid/plans/plan/choose?option=1:2:3'}
        create=Mock(return_value=SessionCreated(session_id='session-test',session_token='private-checkout-token',expires_at=9999999999,plan_id='tirz-1m-sub',status='new'))
        facade=SimpleNamespace(state=SimpleNamespace(publications={'example':SimpleNamespace(portal_site_id='site-a',site_id='example')},session_operations={'create':create}))
        self.app.state.site_api=facade;self.app.state.site_api_store=SimpleNamespace(read=lambda key:{'selection':'1:2:3'})
        with patch.object(self.manager,'policy',return_value={'eligible':True}),patch.object(self.service,'store_catalog',return_value={'plans':[selected]}):
            first=self.client.post(self.path,headers=self.patient_headers,json={'plan_id':selected['plan_id']})
            self.assertEqual(first.status_code,200,first.text)
            second=self.client.post(self.path,headers=self.patient_headers,json={'plan_id':selected['plan_id']})
            self.assertEqual(second.json(),first.json());self.assertEqual(create.call_count,1)
            other=self.client.post(self.path,headers=self.patient_headers,json={'plan_id':'other'})
            self.assertEqual(other.status_code,409)
        self.assertNotIn('private-checkout-token',first.text)
        saved=self.manager.read('site-a',first.json()['id'],self.patient)
        self.assertNotEqual(saved['secret'],'private-checkout-token')
        self.assertEqual(self.manager.cipher().decrypt(saved['secret']),'private-checkout-token')

    def test_six_month_final_window_and_one_time_use_same_policy(self):
        plan=self.service.care.ensure(self.row);data=json.loads(plan['snapshot']);data.update(coverage_days=180,product_setup={'shipment_count':2,'shipment_interval_days':90})
        with self.service.db() as db:db.execute('UPDATE member_care_plans SET snapshot=? WHERE id=?',(json.dumps(data),plan['id']))
        with patch.object(self.service.care,'tasks',return_value=[{'refill_checkpoint':True,'claim':{'status':'claimed'}}]):
            self.service.clock=lambda:NOW+159*86400;self.assertFalse(self.policy()['eligible'])
            self.service.clock=lambda:NOW+160*86400;self.assertTrue(self.policy()['eligible'])
        # Removing recurrence does not relax the supply window.
        data.update(coverage_days=30,product_setup={'shipment_count':1,'shipment_interval_days':30})
        with self.service.db() as db:db.execute('UPDATE member_care_plans SET snapshot=? WHERE id=?',(json.dumps(data),plan['id']))
        with patch.object(self.service.care,'tasks',return_value=[]):
            self.service.clock=lambda:NOW+9*86400;self.assertFalse(self.policy()['eligible'])
            self.service.clock=lambda:NOW+10*86400;self.assertTrue(self.policy()['eligible'])
