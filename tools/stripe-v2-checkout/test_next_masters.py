import json
from pathlib import Path
import sqlite3
import socket
import tempfile
import unittest
from unittest.mock import patch
from import_next_masters import load_catalog, prepare, install
from import_wellness_masters import prepare as wellness
from import_additional_masters import prepare as additional
from member_portal.intake_templates import binding_for_sku, get_template
from catalog_contracts import validate_purchase_pairs


class NextMasterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'checkout.sqlite3'
        self.original = wellness({})
        self.original.update(additional(self.original))
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE admin_config(kind TEXT,id TEXT,data TEXT,PRIMARY KEY(kind,id))')
            db.executemany('INSERT INTO admin_config VALUES(?,?,?)',[(k,i,json.dumps(v)) for (k,i),v in self.original.items()])
            db.execute('CREATE TABLE payments(id TEXT,status TEXT)')
            db.execute("INSERT INTO payments VALUES('held','awaiting_card')")

    def tearDown(self):
        self.temp.cleanup()

    def records(self):
        with sqlite3.connect(self.path) as db:
            return {(k,i):json.loads(v) for k,i,v in db.execute('SELECT kind,id,data FROM admin_config')}

    def test_all_source_pairs_monthly_vs_quarterly_and_intakes(self):
        records = prepare(self.original)
        masters = [v for (k,_),v in records.items() if k == 'master']
        self.assertEqual(len(masters),50)
        self.assertEqual(sum(k=='template_draft' for k,_ in records),6)
        self.assertEqual(sum(k=='purchase_option' for k,_ in records),13)
        validate_purchase_pairs(masters,[p['sku'] for p in load_catalog()['products']])
        for p in load_catalog()['products']:
            for suffix in ('','-SUB'):
                sku=p['sku']+suffix;setup=records['master',sku]['product_setup']
                self.assertEqual(setup['renewal_days'],p['duration_months']*30 if suffix else None)
                self.assertEqual(setup['shipment_days'],list(range(0,p['duration_months']*30,p['supply_days_per_shipment'])))
                self.assertEqual(setup['later_shipment_charge'],'0.00')
                policy=records['refill_policy',sku]
                self.assertFalse(policy['check_in_required']);self.assertEqual(policy['check_in_days'],[])
                self.assertEqual(policy['claim_window_days'],20)
                self.assertEqual(policy['included_refills_enabled'],p['included_refills']>0)
                self.assertTrue(get_template(p['therapy_id'],sku=sku)['questions'])
        yearly=records['master','ALPRO-VAG-0.1%-12M-SUB']['product_setup']
        self.assertEqual(yearly['shipment_days'],list(range(0,360,30)))
        self.assertEqual([day-20 for day in yearly['shipment_days'][1:]],list(range(10,311,30)))
        self.assertEqual(records['master','NAD-INJ-200MG-10ML-12M-SUB']['product_setup']['shipment_days'],[0,90,180,270])

    def test_nad_umbrella_preserves_all_variants_and_prices(self):
        records=prepare(self.original)
        therapy=records['therapy','nad-plus']
        self.assertEqual({t['id'] for t in therapy['treatments']},{'nad-nasal','nad-injectable','nad-rdt-100mg','nad-injectable-200mgml'})
        self.assertFalse(any(k=='therapy' and i.startswith('nad-') and i!='nad-plus' for k,i in records))
        for months in (1,3,6,12):
            plan=records['purchase_option',f'nad-injection-standard-{months}m']
            self.assertEqual(len(plan['skus']),8)
            self.assertIn(f'NAD-INJ-{months}M',plan['skus'])
            self.assertIn(f'NAD-RDT-100MG-{months}M-SUB',plan['skus'])
            self.assertIn(f'NAD-INJ-200MG-10ML-{months}M-SUB',plan['skus'])
        self.assertNotIn(('master','NAD-INJ-12M-SUB'),records)
        self.assertNotIn(('template_draft','master-therapy-nad-plus'),records)

    def test_install_preserves_existing_and_repeat_preserves_edits(self):
        before=self.records()
        with patch.object(socket.socket,'connect',side_effect=AssertionError('No provider calls')):
            self.assertFalse(install(self.path)['applied'])
            self.assertEqual(before,self.records())
            self.assertTrue(install(self.path,True)['applied'])
        after=self.records()
        for key,val in before.items():
            if key!=('therapy','nad-plus'):self.assertEqual(after[key],val,key)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT * FROM payments').fetchall(),[('held','awaiting_card')])
            master=after['master','PROP-20MG-3B'];master['offers'][0]['price']='92.00'
            db.execute("UPDATE admin_config SET data=? WHERE kind='master' AND id='PROP-20MG-3B'",(json.dumps(master),))
        edited=self.records();self.assertTrue(install(self.path,True)['already_imported']);self.assertEqual(edited,self.records())

    def test_late_failure_rolls_back_therapy_changes_and_records(self):
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TRIGGER fail BEFORE INSERT ON admin_config WHEN NEW.id='NAD-INJ-200MG-10ML-12M-SUB' BEGIN SELECT RAISE(ABORT,'test'); END")
        before=self.records()
        with self.assertRaises(sqlite3.IntegrityError):install(self.path,True)
        self.assertEqual(before,self.records())

    def test_admin_template_choices_and_refill_editor(self):
        from test_admin import AdminTests
        helper=AdminTests();helper.setUp()
        try:
            # Seed the prior masters so the combined NAD draft includes all forms.
            for (k,i),v in self.original.items():helper.app.state.admin.put(k,i,v)
            install(helper.app.state.store.path,True)
            state=helper.client.get('/api/admin/state').json()
            ids={'master-therapy-'+f['id'] for f in load_catalog()['families']}
            drafts=[d for d in state['templateDrafts'] if d['id'] in ids]
            self.assertEqual(len(drafts),6)
            for draft in drafts:
                review=helper.review('template_editor',draft)
                self.assertFalse(review['preview']['stickyWrites'])
                self.assertEqual(helper.apply(review).status_code,200)
            for sku in ['ALPRO-VAG-0.1%-12M-SUB','PROP-20MG-3B','RAM-8MG-3M','HYDRABOOST-GEL-3M']:
                response=helper.client.get('/api/admin/master-refill-rules/'+sku)
                self.assertEqual(response.status_code,200)
                self.assertFalse(response.json()['check_in_required'])
            self.assertFalse(helper.fake.calls)
        finally:helper.tearDown()


class MonthlyRefillJourneyTests(unittest.TestCase):
    def test_eleven_included_claims_open_twenty_days_before_each_monthly_delivery(self):
        import test_member_portal as portal
        import test_member_care as care
        from test_wellness_refills import WellnessClaimTests
        from test_member_provider import IncludedCycleSticky
        from catalog_refill_policies import proposed_policy
        h=WellnessClaimTests()
        portal.MemberPortalTests.setUp(h)
        try:
            fake=IncludedCycleSticky(cycles=12,renews=True)
            h.app.state.admin.api=fake;h.app.state.member_portal.provider.api=fake
            care.configure_care_fixture(h.app,fake,12)
            sku='ALPRO-VAG-0.1%-12M-SUB'
            records=prepare({});master=records['master',sku]
            for (k,i),v in records.items():h.app.state.admin.put(k,i,v)
            plan=h.app.state.admin.get('plan_checkout','plan-a')
            plan.update(therapy_id='womens-sexual-health',template_snapshot={'masters':[master]})
            h.app.state.admin.put('plan_checkout','plan-a',plan)
            link=h.app.state.admin.get('link','member-link-a');link['sku']=sku
            h.app.state.admin.put('link','member-link-a',link)
            with h.app.state.store.db() as db:db.execute("UPDATE checkouts SET sku=? WHERE order_id='9001'",(sku,))
            fake.billing_model['days']=30
            line=fake.order['products'][0]
            line.update(sku=sku,recurring_date='2026-11-21',billing_model={'id':'4','days':30,'type':{'id':1}},prepaid=[{'current_cycle':'1','total_cycles':'12','is_renew':'1'}])
            fake.product['sku']=sku
            h.app.state.member_portal.provider.wall_clock=lambda:care.NOW
            rule=records['refill_policy',sku];rule['test_requests_enabled']=True
            h.app.state.admin.put('refill_policy',sku,rule)
            h.fake=fake;h.sku=sku;h.enroll();h.care_path=h.base+'/orders/9001/care-plan'
            self.assertEqual([t['day_offset'] for t in h.journey()['tasks']],list(range(0,360,30)))
            h.complete_initial()
            for day in range(30,360,30):
                h.simulate(day-21);self.assertEqual(h.claim(day).status_code,409)
                h.simulate(day-20);result=h.claim(day)
                self.assertEqual(result.status_code,200,result.text)
                self.assertEqual(result.json()['claim']['amount'],'0.00')
                self.assertEqual(h.claim(day,'repeat-'+str(day)).status_code,200)
            self.assertEqual(h.claim(360).status_code,404)
            self.assertEqual(sum(p=='/api/v1/order_force_bill' for _,p,_ in fake.calls),11)
            self.assertTrue(all(o['products'][0]['sku']==sku for o in fake.orders.values()))
        finally:h.tearDown()
