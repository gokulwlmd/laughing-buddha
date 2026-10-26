"""Verify paired catalog contracts, admin editing, and additive atomic imports."""
import json
from pathlib import Path
import socket
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from import_wellness_masters import install, prepare, load_catalog, THERAPIES
from master import MasterSKU


class WellnessMasterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'checkout.sqlite3'
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE admin_config(kind TEXT,id TEXT,data TEXT,PRIMARY KEY(kind,id))')
            db.execute("INSERT INTO admin_config VALUES('site','untouched','{}')")
            db.execute('CREATE TABLE payments(id TEXT,status TEXT)')
            db.execute("INSERT INTO payments VALUES('open','awaiting_card')")

    def tearDown(self):
        self.temp.cleanup()

    def records(self):
        with sqlite3.connect(self.path) as db:
            return {(k, i): json.loads(v) for k, i, v in db.execute('SELECT kind,id,data FROM admin_config')}

    def test_complete_pairs_and_source_delivery_schedules(self):
        records = prepare({})
        self.assertEqual(sum(k == 'master' for k, _ in records), 34)
        self.assertEqual(sum(k == 'purchase_option' for k, _ in records), 11)
        self.assertEqual(sum(k == 'template_draft' for k, _ in records), 3)
        for p in load_catalog()['products']:
            for recurring in (False, True):
                master = records['master', p['sku'] + ('-SUB' if recurring else '')]
                setup = master['product_setup']
                self.assertEqual(setup['renewal_days'], p['duration_months'] * 30 if recurring else None)
                self.assertEqual(setup['shipment_days'], [i * p['supply_days_per_shipment'] for i in range(p['shipments_per_term'])])
                self.assertEqual(setup['later_shipment_charge'], '0.00')
                self.assertEqual(setup['upfront_price'], p['price'])
                self.assertIsNone(master['product_id'])
                self.assertFalse(setup['processor_verified'])
        self.assertFalse(any(k == 'checkout_template' for k, _ in records))

    def test_exact_source_skus_and_no_unapproved_substitutions(self):
        records = prepare({})
        self.assertIn(('master', 'NADNASAL-3M-SUB'), records)
        self.assertNotIn(('master', 'NAD-NASAL-3M'), records)
        self.assertIn(('master', 'CRM-GLUTATH-1M'), records)
        self.assertIn(('master', 'FINA-1MG-90-30-3B'), records)
        for sku in ('MIN-1MG-FINA-1.25MG', 'NAD-INJ-200MG-10ML-1M', 'NAD-RDT-100MG-1M', 'FINA-1MG-270-30-9B'):
            self.assertNotIn(('master', sku), records)
        # Shared collection membership must not duplicate the master SKU.
        hair = records['therapy_variant_catalog', 'hair-growth']['products']
        fina = next(p for p in hair if p['sku'] == 'FINA-1MG-90-30-3B')
        self.assertEqual(len(fina['collections']), 2)

    def test_preview_and_repeat_preserve_unrelated_and_edited_data(self):
        before = self.records()
        self.assertFalse(install(self.path)['applied'])
        self.assertEqual(before, self.records())
        self.assertEqual(install(self.path, True)['created_records'], 88)
        with sqlite3.connect(self.path) as db:
            record = self.records()['master', 'NAD-INJ-1M']
            record['offers'][0]['price'] = '210.00'
            db.execute("UPDATE admin_config SET data=? WHERE kind='master' AND id='NAD-INJ-1M'", (json.dumps(record),))
            self.assertEqual(db.execute('SELECT * FROM payments').fetchall(), [('open', 'awaiting_card')])
        edited = self.records()
        self.assertTrue(install(self.path, True)['already_imported'])
        self.assertEqual(edited, self.records())
        self.assertEqual(before['site', 'untouched'], edited['site', 'untouched'])

    def test_conflict_and_write_failure_roll_back_whole_batch(self):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO admin_config VALUES('sku','GLUTA-12M-SUB','{}')")
        before = self.records()
        with self.assertRaisesRegex(ValueError, 'Existing record'):
            install(self.path, True)
        self.assertEqual(before, self.records())
        with sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM admin_config WHERE kind='sku'")
            db.execute("CREATE TRIGGER abort_import BEFORE INSERT ON admin_config WHEN NEW.id='GLUTA-12M-SUB' BEGIN SELECT RAISE(ABORT,'test'); END")
        before = self.records()
        with self.assertRaises(sqlite3.IntegrityError):
            install(self.path, True)
        self.assertEqual(before, self.records())

    def test_missing_record_or_changed_source_blocks_rerun(self):
        install(self.path, True)
        catalog = load_catalog()
        catalog['products'][0]['price'] = '888.00'
        with patch('import_wellness_masters.load_catalog', return_value=catalog):
            with self.assertRaisesRegex(ValueError, 'Catalog changed'):
                install(self.path, True)
        with sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM admin_config WHERE kind='template_draft'")
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            install(self.path, True)

    def test_no_network_and_no_missing_database_creation(self):
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('No provider calls')):
            self.assertEqual(install(self.path, True)['sticky_writes'], 0)
        missing = self.path.parent / 'missing.sqlite3'
        with self.assertRaises(FileNotFoundError):
            install(missing, True)
        self.assertFalse(missing.exists())

    def test_admin_visibility_and_price_editing(self):
        from test_admin import AdminTests
        helper = AdminTests()
        helper.setUp()
        try:
            install(helper.app.state.store.path, True)
            state = helper.client.get('/api/admin/state').json()
            self.assertEqual(len([m for m in state['masters'] if m['therapy_id'] in THERAPIES]), 34)
            for draft in state['templateDrafts']:
                if draft['therapy_id'] in THERAPIES:
                    review = helper.review('template_editor', draft)
                    self.assertFalse(review['preview']['stickyWrites'])
                    self.assertEqual(helper.apply(review).status_code, 200)
            master = next(m for m in state['masters'] if m['sku'] == 'NADNASAL-6M-SUB')
            request = {k: v for k, v in master.items() if k in MasterSKU.model_fields}
            request['offers'][0]['price'] = '777.00'
            self.assertEqual(helper.apply(helper.review('master', request)).status_code, 200)
            self.assertEqual(helper.app.state.admin.get('master', master['sku'])['offers'][0]['price'], '777.00')
            self.assertFalse(helper.fake.calls)
        finally:
            helper.tearDown()


if __name__ == '__main__':
    unittest.main()
