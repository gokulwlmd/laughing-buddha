"""ED master import: exact variants, delivery contracts and additive writes."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from import_ed_master import install, load_catalog, prepare, THERAPY_ID, TEMPLATE_ID, _legacy_records, LEGACY_RUN_ID
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
        self.assertEqual(len(masters), 176)
        for m in masters:
            MasterSKU.model_validate({k: v for k, v in m.items() if k in MasterSKU.model_fields})
            self.assertIsNone(m['product_id'])
            self.assertEqual(m['offers'][0]['billing_models'], [])
        plans = [v for (k, _), v in records.items() if k == 'purchase_option']
        self.assertEqual(len(plans), 12)
        self.assertEqual(sum(len(p['skus']) for p in plans), 176)
        for p in plans:
            PurchaseOption.model_validate({k: v for k, v in p.items() if k != 'revision'})
            self.assertLessEqual(len(p['skus']), 20)
        TemplateEditor.model_validate(records['template_draft', TEMPLATE_ID])
        self.assertFalse(any(k == 'checkout_template' for k, _ in records))

    def test_full_term_renewal_and_free_intermediate_shipments(self):
        records = prepare({})
        for p in load_catalog()['products']:
            once = records['master', p['sku']]['product_setup']
            self.assertIsNone(once['renewal_days'])
            self.assertIsNone(once['renewal_months'])
            setup = records['master', p['sku'] + '-SUB']['product_setup']
            self.assertEqual(once['shipment_days'], setup['shipment_days'])
            self.assertEqual(once['upfront_price'], setup['upfront_price'])
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
        self.assertEqual(result['created_records'], 367)
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

    def legacy_fixture(self):
        rows = _legacy_records({})
        with sqlite3.connect(self.path) as db:
            for (kind, key), data in rows.items():
                db.execute('INSERT INTO admin_config VALUES(?,?,?)', (kind, key, json.dumps(data)))
            db.execute('CREATE TABLE admin_setup_runs(id TEXT PRIMARY KEY,created REAL,details TEXT)')
            db.execute('INSERT INTO admin_setup_runs VALUES(?,?,?)', (LEGACY_RUN_ID, 1, json.dumps({'created_records': list(rows)})))

    def test_repairs_legacy_draft_and_preserves_price_and_schedule_edits(self):
        from master import planned_product_setup
        self.legacy_fixture()
        with sqlite3.connect(self.path) as db:
            key = ('master', 'SILD-50MG-72-6-12B')
            row = self.records()[key]
            row['offers'][0]['price'] = '600.00'
            row['planning_contract'].update(shipments_per_term=6, shipment_interval=60)
            row['product_setup'] = planned_product_setup(row)
            db.execute('UPDATE admin_config SET data=? WHERE kind=? AND id=?', (json.dumps(row), *key))
        before = self.records()
        preview = install(self.path)
        self.assertEqual(preview['planned_new_records'], 176)
        self.assertEqual(self.records(), before)
        result = install(self.path, True)
        self.assertEqual(result['master_skus'], 176)
        after = self.records()
        self.assertEqual(after['site', 'existing'], before['site', 'existing'])
        for suffix in ('', '-SUB'):
            row = after['master', 'SILD-50MG-72-6-12B' + suffix]
            self.assertEqual(row['offers'][0]['price'], '600.00')
            self.assertEqual(row['product_setup']['shipment_days'], [0, 60, 120, 180, 240, 300])
        self.assertIsNone(after['master', 'SILD-50MG-72-6-12B']['planning_contract']['renewal_months'])
        self.assertEqual(after['master', 'SILD-50MG-72-6-12B-SUB']['planning_contract']['renewal_months'], 12)
        self.assertTrue(install(self.path, True)['already_imported'])

    def test_repair_refuses_published_assigned_or_changed_ed(self):
        self.legacy_fixture()
        for kind, data in [('assignment', {'sku': 'SILD-50MG-6-6-1B'}),
                           ('checkout_template', {'therapy_id': THERAPY_ID}),
                           ('link', {'sku': 'SILD-50MG-6-6-1B'})]:
            with sqlite3.connect(self.path) as db:
                db.execute('INSERT INTO admin_config VALUES(?,?,?)', (kind, 'linked-ed', json.dumps(data)))
            before = self.records()
            with self.assertRaisesRegex(ValueError, 'referenced outside'):
                install(self.path, True)
            self.assertEqual(self.records(), before)
            with sqlite3.connect(self.path) as db:
                db.execute('DELETE FROM admin_config WHERE kind=? AND id=?', (kind, 'linked-ed'))
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE admin_config SET data='{}' WHERE kind='template_draft'")
        before = self.records()
        with self.assertRaisesRegex(ValueError, 'draft changed'):
            install(self.path, True)
        self.assertEqual(self.records(), before)

    def test_repair_rolls_back_updates_if_sub_insert_fails(self):
        self.legacy_fixture()
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TRIGGER fail_sub BEFORE INSERT ON admin_config WHEN NEW.id LIKE '%-SUB' BEGIN SELECT RAISE(ABORT,'test failure'); END")
        before = self.records()
        with self.assertRaises(sqlite3.IntegrityError):
            install(self.path, True)
        self.assertEqual(self.records(), before)

    def test_pair_guard_rejects_missing_sub_and_wrong_renewal(self):
        import copy
        from catalog_contracts import validate_purchase_pairs
        records = prepare({})
        masters = [v for (k, _), v in records.items() if k == 'master']
        bases = [p['sku'] for p in load_catalog()['products']]
        for mutate in (
            lambda rows: rows.pop(),
            lambda rows: rows[0]['planning_contract'].update(renewal_months=1),
            lambda rows: rows[1]['planning_contract'].update(renewal_months=None),
            lambda rows: rows[1]['planning_contract'].update(shipments_per_term=2, shipment_interval=15),
        ):
            changed = copy.deepcopy(masters)
            mutate(changed)
            with self.assertRaises(ValueError):
                validate_purchase_pairs(changed, bases)


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
            self.assertEqual(len([m for m in state['masters'] if m['therapy_id'] == THERAPY_ID]), 176)
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
