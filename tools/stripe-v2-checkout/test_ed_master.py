"""ED master import: exact variants, delivery contracts and additive writes."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from import_ed_master import install, load_catalog, prepare, THERAPY_ID, TEMPLATE_ID
from plans import Therapy, PurchaseOption
from master import MasterSKU
from sites import TemplateEditor


class EDMasterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'checkout.sqlite3'
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE admin_config(kind TEXT,id TEXT,data TEXT,PRIMARY KEY(kind,id))')
            db.execute('INSERT INTO admin_config VALUES(?,?,?)', ('site', 'existing', '{"id":"existing"}'))
            db.execute('CREATE TABLE payments(id TEXT,status TEXT)')
            db.execute("INSERT INTO payments VALUES('untouched','awaiting_card')")

    def tearDown(self):
        self.temp.cleanup()

    def records(self):
        with sqlite3.connect(self.path) as db:
            return {(k, i): json.loads(v) for k, i, v in db.execute('SELECT kind,id,data FROM admin_config')}

    def test_complete_matrix_and_existing_admin_models(self):
        records = prepare({})
        therapy = records['therapy', THERAPY_ID]
        Therapy.model_validate({k: v for k, v in therapy.items() if k != 'revision'})
        self.assertEqual(len(therapy['treatments']), 3)
        masters = [v for (k, _), v in records.items() if k == 'master']
        self.assertEqual(len(masters), 88)
        for m in masters:
            MasterSKU.model_validate({k: v for k, v in m.items() if k in MasterSKU.model_fields})
            self.assertIsNone(m['product_id'])
            self.assertEqual(m['offers'][0]['billing_models'], [])
        plans = [v for (k, _), v in records.items() if k == 'purchase_option']
        self.assertEqual(len(plans), 12)
        self.assertEqual(sum(len(p['skus']) for p in plans), 88)
        for p in plans:
            PurchaseOption.model_validate({k: v for k, v in p.items() if k != 'revision'})
            self.assertLessEqual(len(p['skus']), 10)
        TemplateEditor.model_validate(records['template_draft', TEMPLATE_ID])
        self.assertFalse(any(k == 'checkout_template' for k, _ in records))

    def test_full_term_renewal_and_free_intermediate_shipments(self):
        records = prepare({})
        for p in load_catalog()['products']:
            setup = records['master', p['sku']]['product_setup']
            months = p['duration_months']
            self.assertEqual(setup['renewal_days'], months * 30)
            self.assertEqual(setup['shipment_count'], {1: 1, 3: 1, 6: 2, 12: 4}[months])
            self.assertEqual(setup['shipment_days'], {1: [0], 3: [0], 6: [0, 90], 12: [0, 90, 180, 270]}[months])
            self.assertEqual(setup['later_shipment_charge'], '0.00')
            self.assertFalse(setup['processor_verified'])

    def test_preview_does_not_write_and_apply_preserves_unrelated_data(self):
        before = self.records()
        self.assertFalse(install(self.path)['applied'])
        self.assertEqual(self.records(), before)
        result = install(self.path, True)
        self.assertEqual(result['created_records'], 191)
        self.assertEqual(self.records()['site', 'existing'], before['site', 'existing'])
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT * FROM payments').fetchall(), [('untouched', 'awaiting_card')])

    def test_repeat_preserves_owner_price_edits(self):
        install(self.path, True)
        with sqlite3.connect(self.path) as db:
            key = ('master', 'SILD-50MG-6-6-1B')
            record = self.records()[key]
            record['offers'][0]['price'] = '123.00'
            db.execute('UPDATE admin_config SET data=? WHERE kind=? AND id=?', (json.dumps(record), *key))
        before = self.records()
        self.assertTrue(install(self.path, True)['already_imported'])
        self.assertEqual(self.records(), before)

    def test_conflict_and_interrupted_import_fail_without_partial_rows(self):
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO admin_config VALUES(?,?,?)', ('sku', 'TADA-5MG-360-30-12B', '{}'))
        before = self.records()
        with self.assertRaisesRegex(ValueError, 'Existing record'):
            install(self.path, True)
        self.assertEqual(self.records(), before)
        with sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM admin_config WHERE kind='sku'")
            db.execute("CREATE TRIGGER fail_insert BEFORE INSERT ON admin_config WHEN NEW.kind='purchase_option' BEGIN SELECT RAISE(ABORT,'test failure'); END")
        before = self.records()
        with self.assertRaises(sqlite3.IntegrityError):
            install(self.path, True)
        self.assertEqual(self.records(), before)

    def test_missing_record_on_rerun_requires_reconciliation(self):
        install(self.path, True)
        with sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM admin_config WHERE kind='therapy_variant_catalog'")
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            install(self.path, True)

    def test_no_network_or_application_startup(self):
        import socket
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('No network')):
            self.assertEqual(install(self.path, True)['sticky_writes'], 0)

    def test_missing_database_is_not_created(self):
        missing = self.path.parent / 'missing.sqlite3'
        with self.assertRaises(FileNotFoundError):
            install(missing, True)
        self.assertFalse(missing.exists())


class EDAdminVisibilityTests(unittest.TestCase):
    def test_import_is_visible_and_editable_through_existing_admin_api(self):
        from test_admin import AdminTests
        helper = AdminTests()
        helper.setUp()
        try:
            install(helper.app.state.store.path, True)
            response = helper.client.get('/api/admin/state')
            self.assertEqual(response.status_code, 200)
            state = response.json()
            self.assertEqual(len([m for m in state['masters'] if m['therapy_id'] == THERAPY_ID]), 88)
            self.assertEqual(len([p for p in state['purchaseOptions'] if p['therapy_id'] == THERAPY_ID]), 12)
            draft = next(d for d in state['templateDrafts'] if d['id'] == TEMPLATE_ID)
            review = helper.review('template_editor', draft)
            self.assertEqual(review['preview']['stickyWrites'], [])
            self.assertEqual(helper.apply(review).status_code, 200)
            master = next(m for m in state['masters'] if m['sku'] == 'SILD-50MG-6-6-1B')
            request = {k: v for k, v in master.items() if k in MasterSKU.model_fields}
            request['offers'][0]['price'] = '55.00'
            self.assertEqual(helper.apply(helper.review('master', request)).status_code, 200)
            self.assertEqual(helper.app.state.admin.get('master', master['sku'])['offers'][0]['price'], '55.00')
            self.assertFalse(helper.app.state.admin.records('checkout_template'))
            self.assertFalse(helper.fake.calls)
        finally:
            helper.tearDown()


if __name__ == '__main__':
    unittest.main()
