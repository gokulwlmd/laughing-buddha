import json
from pathlib import Path
import sqlite3
import socket
import tempfile
import unittest
from unittest.mock import patch
from import_ed_advanced import load_catalog,prepare,install
from catalog_contracts import validate_purchase_pairs
from member_portal.intake_templates import binding_for_sku,get_template


class EDCombinationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'test.sqlite3'
        self.old={('therapy','erectile-dysfunction'):dict(id='erectile-dysfunction',name='ED',enabled=True,treatments=[dict(id='astv-5pack',name='4-in-1 ED blend')]),('template_draft','existing-ed'):{'keep':True}}
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE admin_config(kind TEXT,id TEXT,data TEXT,PRIMARY KEY(kind,id))')
            db.executemany('INSERT INTO admin_config VALUES(?,?,?)',[(k,i,json.dumps(v)) for (k,i),v in self.old.items()])
            db.execute('CREATE TABLE payments(id TEXT,status TEXT)');db.execute("INSERT INTO payments VALUES('old','held')")
    def tearDown(self):self.tmp.cleanup()
    def records(self):
        with sqlite3.connect(self.path) as db:return {(k,i):json.loads(v) for k,i,v in db.execute('SELECT kind,id,data FROM admin_config')}
    def test_all_pairs_selection_quantity_and_care_rules(self):
        result=prepare(self.old);masters=[v for (k,_),v in result.items() if k=='master']
        self.assertEqual(len(masters),24)
        validate_purchase_pairs(masters,[p['sku'] for p in load_catalog()['products']])
        for p in load_catalog()['products']:
            for suffix in ('','-SUB'):
                sku=p['sku']+suffix;m=result['master',sku];setup=m['product_setup'];rule=result['refill_policy',sku]
                self.assertIn(p['name'],m['name'])
                self.assertEqual(setup['shipment_days'],list(range(0,p['duration_months']*30,p['supply_days_per_shipment'])))
                self.assertEqual(setup['renewal_days'],p['duration_months']*30 if suffix else None)
                self.assertEqual(p['tablets_per_shipment']*setup['shipment_count'],p['total_tablets'])
                self.assertEqual(rule['included_refills_enabled'],p['duration_months']>=6)
                self.assertEqual(rule['claim_window_days'],20);self.assertFalse(rule['check_in_required'])
                self.assertTrue(rule['initial_intake_required'])
                self.assertTrue(get_template('erectile-dysfunction',sku=sku)['questions'])
        draft=result['template_draft','master-therapy-ed-pt141-vardenafil-combinations']
        self.assertEqual(len(draft['plans']),4)
        for plan in draft['plans']:self.assertEqual(len(plan['skus']),6)
        self.assertEqual(len(result['therapy','erectile-dysfunction']['treatments']),4)
    def test_atomic_install_and_preserved_prices(self):
        with patch.object(socket.socket,'connect',side_effect=AssertionError('No provider writes')):
            install(self.path);self.assertEqual(self.records(),self.old);install(self.path,True)
        records=self.records();self.assertEqual(records['template_draft','existing-ed'],self.old['template_draft','existing-ed'])
        sku='TADA-OXYT-PT141-RDT-10MG-100IU-1MG-1M';records['master',sku]['offers'][0]['price']='123.00'
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE admin_config SET data=? WHERE kind='master' AND id=?",(json.dumps(records['master',sku]),sku))
            self.assertEqual(db.execute('SELECT * FROM payments').fetchall(),[('old','held')])
        self.assertTrue(install(self.path,True)['already_imported']);self.assertEqual(self.records(),records)
    def test_late_failure_rolls_back_everything(self):
        with sqlite3.connect(self.path) as db:db.execute("CREATE TRIGGER fail BEFORE INSERT ON admin_config WHEN NEW.id='TADA-VARD-RDT-5MG-5MG-12M-SUB' BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):install(self.path,True)
        self.assertEqual(self.records(),self.old)

class EDQuarterlyRefillJourneyTests(unittest.TestCase):
    def test_three_included_claims_keep_same_sku_and_stop_at_term_end(self):
        import test_member_portal as portal
        import test_member_care as care
        from test_wellness_refills import WellnessClaimTests
        from test_member_provider import IncludedCycleSticky
        from catalog_refill_policies import proposed_policy
        h=WellnessClaimTests()
        portal.MemberPortalTests.setUp(h)
        try:
            fake=IncludedCycleSticky(cycles=4,renews=True)
            h.app.state.admin.api=fake;h.app.state.member_portal.provider.api=fake
            care.configure_care_fixture(h.app,fake,12)
            sku='TADA-OXYT-PT141-RDT-20MG-100IU-2MG-12M-SUB'
            records=prepare({});master=records['master',sku]
            for (k,i),v in records.items():h.app.state.admin.put(k,i,v)
            plan=h.app.state.admin.get('plan_checkout','plan-a')
            plan.update(therapy_id='erectile-dysfunction',template_snapshot={'masters':[master]})
            h.app.state.admin.put('plan_checkout','plan-a',plan)
            link=h.app.state.admin.get('link','member-link-a');link['sku']=sku
            h.app.state.admin.put('link','member-link-a',link)
            with h.app.state.store.db() as db:db.execute("UPDATE checkouts SET sku=? WHERE order_id='9001'",(sku,))
            fake.billing_model['days']=90
            line=fake.order['products'][0]
            line.update(sku=sku,recurring_date='2027-01-20',billing_model={'id':'4','days':90,'type':{'id':1}},prepaid=[{'current_cycle':'1','total_cycles':'4','is_renew':'1'}])
            fake.product['sku']=sku
            h.app.state.member_portal.provider.wall_clock=lambda:care.NOW
            rule=records['refill_policy',sku];rule['test_requests_enabled']=True
            h.app.state.admin.put('refill_policy',sku,rule)
            h.fake=fake;h.sku=sku;h.enroll();h.care_path=h.base+'/orders/9001/care-plan'
            self.assertEqual([t['day_offset'] for t in h.journey()['tasks']],[0,90,180,270])
            h.complete_initial()
            for day in (90,180,270):
                h.simulate(day-21);self.assertEqual(h.claim(day).status_code,409)
                h.simulate(day-20);result=h.claim(day)
                self.assertEqual(result.status_code,200,result.text)
                self.assertEqual(result.json()['claim']['amount'],'0.00')
                self.assertEqual(h.claim(day,'repeat-'+str(day)).status_code,200)
            self.assertEqual(h.claim(360).status_code,404)
            self.assertEqual(sum(p=='/api/v1/order_force_bill' for _,p,_ in fake.calls),3)
            self.assertTrue(all(o['products'][0]['sku']==sku for o in fake.orders.values()))
        finally:h.tearDown()
