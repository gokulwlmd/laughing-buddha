import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from fastapi import HTTPException
from import_astv_masters import install, prepare, THERAPY
from import_wellness_masters import CatalogView


class ASTVMasterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'test.sqlite3'
        self.old = {('therapy', THERAPY): dict(id=THERAPY, name='ED', enabled=True,
                    treatments=[dict(id='sildenafil', name='Sildenafil')]),
                    ('template_draft', 'existing-ed'): {'preserve': True}}
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE admin_config(kind TEXT,id TEXT,data TEXT,PRIMARY KEY(kind,id))')
            db.executemany('INSERT INTO admin_config VALUES(?,?,?)', [(k,i,json.dumps(v)) for (k,i),v in self.old.items()])

    def tearDown(self):
        self.tmp.cleanup()

    def rows(self):
        with sqlite3.connect(self.path) as db:
            return {(k,i):json.loads(v) for k,i,v in db.execute('SELECT kind,id,data FROM admin_config')}

    def test_exact_pairs_unknown_deliveries_and_assignment_block(self):
        pending = prepare(self.old)
        view = CatalogView(self.old | pending)
        for m in (1,3,6,12):
            for suffix in ('','-SUB'):
                value = pending['master',f'ASTV-5P-{m}M{suffix}']
                setup = value['product_setup']
                self.assertEqual(setup['renewal_days'],m*30 if suffix else None)
                self.assertEqual(setup['shipment_count'],1 if m==1 else None)
                self.assertEqual(setup['shipment_days'],[0] if m==1 else [])
                with self.assertRaises(HTTPException):view.activated_master(value)
        self.assertEqual(len(pending['template_draft','master-therapy-astv-5pack']['plans']),4)
        self.assertFalse(any(k=='refill_policy' for k,_ in pending))

    def test_preview_idempotency_and_price_preservation(self):
        install(self.path)
        self.assertEqual(self.rows(),self.old)
        install(self.path,True)
        rows=self.rows()
        self.assertEqual(rows['template_draft','existing-ed'],self.old['template_draft','existing-ed'])
        rows['master','ASTV-5P-1M']['offers'][0]['price']='77.00'
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE admin_config SET data=? WHERE kind='master' AND id='ASTV-5P-1M'",(json.dumps(rows['master','ASTV-5P-1M']),))
        self.assertTrue(install(self.path,True)['already_imported'])
        self.assertEqual(self.rows(),rows)

    def test_late_failure_rolls_back(self):
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TRIGGER fail BEFORE INSERT ON admin_config WHEN NEW.id='ASTV-5P-12M-SUB' BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):install(self.path,True)
        self.assertEqual(self.rows(),self.old)


if __name__ == '__main__':unittest.main()
