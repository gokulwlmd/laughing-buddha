import json
from pathlib import Path
import socket
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from import_skin_topicals import load_catalog, prepare, install, UREA_SKU
from import_next_masters import prepare as earlier_masters
from catalog_contracts import validate_purchase_pairs
from catalog_refill_policies import source_binding
from member_portal.intake_templates import get_template


class SkinTopicalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'test.sqlite3'
        self.old = earlier_masters({})
        self.old['master','HYDRABOOST-GEL-1M']['offers'][0]['price'] = '71.00'
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE admin_config(kind TEXT,id TEXT,data TEXT,PRIMARY KEY(kind,id))')
            db.executemany('INSERT INTO admin_config VALUES(?,?,?)',[(k,i,json.dumps(v)) for (k,i),v in self.old.items()])
            db.execute('CREATE TABLE payments(id TEXT,status TEXT)')
            db.execute("INSERT INTO payments VALUES('old','held')")

    def tearDown(self):
        self.tmp.cleanup()

    def records(self):
        with sqlite3.connect(self.path) as db:
            return {(k,i):json.loads(v) for k,i,v in db.execute('SELECT kind,id,data FROM admin_config')}

    def test_pairs_delivery_and_combined_skin_template(self):
        result = prepare(self.old)
        masters = [v for (k,_),v in result.items() if k == 'master']
        self.assertEqual(len(masters),16)
        validate_purchase_pairs(masters,[p['sku'] for p in load_catalog()['products']])
        for p in load_catalog()['products']:
            for suffix in ('','-SUB'):
                sku=p['sku']+suffix; m=result['master',sku]; setup=m['product_setup']; rule=result['refill_policy',sku]
                self.assertEqual(setup['shipment_days'],[0])
                self.assertEqual(setup['shipment_count'],1)
                self.assertEqual(setup['renewal_days'],p['supply_days_per_shipment'] if suffix else None)
                self.assertFalse(rule['included_refills_enabled'])
                self.assertFalse(rule['check_in_required'])
                self.assertTrue(rule['initial_intake_required'])
                self.assertEqual(rule['allow_paid_early_renewal'],bool(suffix))
                self.assertTrue(get_template('skin-care',sku=sku)['questions'])
                self.assertEqual(source_binding(sku)['template_id'],'skin-care')
        draft = result['template_draft','master-therapy-skin-care-topicals']
        self.assertEqual([p['duration_months'] for p in draft['plans']],[1,3])
        self.assertEqual([len(p['skus']) for p in draft['plans']],[12,10])
        skus={s for p in draft['plans'] for s in p['skus']}
        self.assertIn('HYDRABOOST-GEL-1M',skus)
        self.assertIn('C-DERM-CREAM2-1M-SUB',skus)
        self.assertIn(UREA_SKU,skus)
        self.assertIn(UREA_SKU+'-SUB',skus)
        self.assertIn('Urea',source_binding(UREA_SKU)['product_name'])
        self.assertEqual(len(result['therapy','skin-care']['treatments']),6)

    def test_preview_preservation_and_repeat(self):
        with patch.object(socket.socket,'connect',side_effect=AssertionError('No provider writes')):
            install(self.path)
            self.assertEqual(self.records(),self.old)
            install(self.path,True)
        records=self.records()
        for key,value in self.old.items():
            if key != ('therapy','skin-care'):
                self.assertEqual(records[key],value)
        sku='DERM-EST-VC-HYA-TOPICAL';records['master',sku]['offers'][0]['price']='68.00'
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE admin_config SET data=? WHERE kind='master' AND id=?",(json.dumps(records['master',sku]),sku))
            self.assertEqual(db.execute('SELECT * FROM payments').fetchall(),[('old','held')])
        self.assertTrue(install(self.path,True)['already_imported'])
        self.assertEqual(self.records(),records)

    def test_failure_rolls_back(self):
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TRIGGER fail BEFORE INSERT ON admin_config WHEN NEW.kind='template_draft' BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):install(self.path,True)
        self.assertEqual(self.records(),self.old)

    def test_conflict_refused(self):
        records=dict(self.old)
        records['master','DERM-EST-VC-HYA-TOPICAL']={'keep':True}
        with self.assertRaises(HTTPException) as caught:prepare(records)
        self.assertEqual(caught.exception.status_code,409)
