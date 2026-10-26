import copy
import json
from pathlib import Path
import socket
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from import_additional_masters import install, prepare, load_catalog
from import_wellness_masters import prepare as wellness
from member_portal.intake_templates import binding_for_sku, get_template
from refill_rules import SaveRefillRules, validate_included_policy


class AdditionalMasterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'checkout.sqlite3'
        self.original = wellness({})
        for tid in ('pt-141', 'sermorelin'):
            self.original['therapy', tid] = dict(id=tid, name=tid, enabled=True, revision=4, treatments=[dict(id=tid, name=tid)])
        self.original['site', 'untouched'] = {'revision': 7}
        self.original['template_draft', 'master-therapy-4'] = {'untouched': True}
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE admin_config(kind TEXT,id TEXT,data TEXT,PRIMARY KEY(kind,id))')
            db.executemany('INSERT INTO admin_config VALUES(?,?,?)', [(k,i,json.dumps(v)) for (k,i),v in self.original.items()])
            db.execute('CREATE TABLE payments(id TEXT,status TEXT)')
            db.execute("INSERT INTO payments VALUES('open','awaiting_card')")

    def tearDown(self):
        self.temp.cleanup()

    def records(self):
        with sqlite3.connect(self.path) as db:
            return {(k,i):json.loads(v) for k,i,v in db.execute('SELECT kind,id,data FROM admin_config')}

    def test_source_skus_and_delivery_contracts_and_intake(self):
        records = prepare(self.original)
        self.assertEqual(sum(k=='master' for k,_ in records),30)
        self.assertEqual(sum(k=='template_draft' for k,_ in records),4)
        self.assertEqual(sum(k=='purchase_option' for k,_ in records),15)
        self.assertEqual(sum(k=='refill_policy' for k,_ in records),30)
        expected = {prefix+f'-{m}M' for prefix in ('PT141-NASAL-5MG','NAD-RDT-100MG','SERM-RDT-500MCG') for m in (1,3,6,12)}
        expected |= {f'SERT-25MG-{m*30}-30-{m}B' for m in (3,6,12)}
        self.assertEqual({p['sku'] for p in load_catalog()['products']},expected)
        for p in load_catalog()['products']:
            plan = records['purchase_option',f"{p['family_id']}-{p['duration_months']}m"]
            self.assertEqual(plan['skus'],[p['sku'],p['sku']+'-SUB'])
            for recurring in (False,True):
                sku=p['sku']+('-SUB' if recurring else '')
                master=records['master',sku];setup=master['product_setup']
                self.assertIsNone(master['product_id'])
                self.assertEqual(setup['renewal_days'],p['duration_months']*30 if recurring else None)
                self.assertEqual(setup['shipment_days'],[i*p['supply_days_per_shipment'] for i in range(p['shipments_per_term'])])
                self.assertEqual(setup['upfront_price'],p['price'])
                self.assertEqual(setup['later_shipment_charge'],'0.00')
                policy=records['refill_policy',sku]
                self.assertEqual(policy['included_refills_enabled'],p['included_refills']>0)
                self.assertFalse(policy['check_in_required'])
                self.assertEqual(policy['check_in_days'],[])
                self.assertEqual(policy['claim_window_days'],20)
                binding=binding_for_sku(sku)
                template=get_template(binding['template_id'],sku=sku)
                self.assertEqual(template['kind'],'initial')
                self.assertTrue(template['questions'])
                body=SaveRefillRules.model_validate({k:v for k,v in policy.items() if k not in ('sku','revision')}|{'expected_revision':1})
                validate_included_policy(body,binding,setup)

    def test_additive_idempotent_and_no_network(self):
        before=self.records()
        with patch.object(socket.socket,'connect',side_effect=AssertionError('No provider writes')):
            self.assertFalse(install(self.path)['applied'])
            self.assertEqual(before,self.records())
            self.assertTrue(install(self.path,True)['applied'])
        after=self.records()
        for key,value in before.items():
            if key[0]=='therapy' and key[1] in ('nad-plus','pt-141','sermorelin'):
                self.assertTrue(all(t in after[key]['treatments'] for t in value['treatments']))
            else:self.assertEqual(value,after[key],key)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT * FROM payments').fetchall(),[('open','awaiting_card')])
            m=after['master','NAD-RDT-100MG-1M'];m['offers'][0]['price']='111.00'
            db.execute("UPDATE admin_config SET data=? WHERE kind='master' AND id='NAD-RDT-100MG-1M'",(json.dumps(m),))
        edited=self.records()
        self.assertTrue(install(self.path,True)['already_imported'])
        self.assertEqual(edited,self.records())

    def test_collision_and_mid_write_failure_roll_back(self):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO admin_config VALUES('sku','SERT-25MG-360-30-12B-SUB','{}')")
        before=self.records()
        with self.assertRaisesRegex(ValueError,'Existing record'):
            install(self.path,True)
        self.assertEqual(before,self.records())
        with sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM admin_config WHERE id='SERT-25MG-360-30-12B-SUB'")
            db.execute("CREATE TRIGGER fail BEFORE INSERT ON admin_config WHEN NEW.id='SERT-25MG-360-30-12B-SUB' BEGIN SELECT RAISE(ABORT,'test'); END")
        before=self.records()
        with self.assertRaises(sqlite3.IntegrityError):install(self.path,True)
        self.assertEqual(before,self.records())

    def test_missing_records_and_changed_catalog_block_repeat(self):
        install(self.path,True)
        catalog=load_catalog();catalog['products'][0]['price']='555.00'
        with patch('import_additional_masters.load_catalog',return_value=catalog):
            with self.assertRaisesRegex(ValueError,'Catalog changed'):install(self.path,True)
        with sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM admin_config WHERE kind='refill_policy' AND id='PT141-NASAL-5MG-1M'")
        with self.assertRaisesRegex(ValueError,'Incomplete'):install(self.path,True)

    def test_admin_drafts_and_price_editing(self):
        from test_admin import AdminTests
        from master import MasterSKU
        helper=AdminTests();helper.setUp()
        try:
            install(helper.app.state.store.path,True)
            state=helper.client.get('/api/admin/state').json()
            names={'master-therapy-'+f['id'] for f in load_catalog()['families']}
            drafts=[d for d in state['templateDrafts'] if d['id'] in names]
            self.assertEqual(len(drafts),4)
            for d in drafts:
                review=helper.review('template_editor',d)
                self.assertFalse(review['preview']['stickyWrites'])
                self.assertEqual(helper.apply(review).status_code,200)
            m=next(m for m in state['masters'] if m['sku']=='SERT-25MG-360-30-12B-SUB')
            request={k:v for k,v in m.items() if k in MasterSKU.model_fields}
            request['offers'][0]['price']='299.00'
            self.assertEqual(helper.apply(helper.review('master',request)).status_code,200)
            self.assertFalse(helper.fake.calls)
        finally:helper.tearDown()
