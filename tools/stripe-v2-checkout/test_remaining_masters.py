import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from import_remaining_masters import load_catalog, prepare, install
from catalog_contracts import validate_purchase_pairs
from member_portal.intake_templates import binding_for_sku, get_template
from import_wellness_masters import CatalogView


class RemainingCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_catalog()
        cls.prepared = prepare({})

    def test_complete_row_accounting_and_no_costs(self):
        rows = self.data['review']
        self.assertEqual(len(rows), 788)
        self.assertEqual(len({r['source_row'] for r in rows}), 788)
        self.assertEqual(sum(r['status']=='Finalized structure' for r in rows),306)
        self.assertEqual(sum(r['status']=='Needs clarification' for r in rows),243)
        self.assertEqual(sum(r['status']=='Existing master' for r in rows),239)
        self.assertNotIn('Product Cost',json.dumps(self.data))

    def test_pairs_refills_and_intake_bindings(self):
        masters=[v for (kind,_),v in self.prepared.items() if kind=='master']
        validate_purchase_pairs(masters,[p['sku'] for p in self.data['products']])
        self.assertEqual(len(masters),612)
        for p in self.data['products']:
            for suffix in ('','-SUB'):
                sku=p['sku']+suffix;m=self.prepared['master',sku];policy=self.prepared['refill_policy',sku]
                self.assertEqual(m['product_setup']['shipment_days'],list(range(0,p['duration_months']*30,p['supply_days_per_shipment'])))
                self.assertEqual(m['product_setup']['renewal_days'],p['duration_months']*30 if suffix else None)
                self.assertEqual(policy['check_in_required'],p['check_in_required'])
                self.assertEqual(policy['claim_window_days'],20)
                self.assertEqual(policy['included_refills_enabled'],p['included_refills']>0)
                self.assertIsNotNone(binding_for_sku(sku))
                self.assertTrue(get_template(p['therapy_id'],sku=sku)['questions'])

    def test_uncertain_rows_cannot_enter_checkout(self):
        held=[r for r in self.data['review'] if r['status']=='Needs clarification']
        for r in held:
            self.assertNotIn(('master',r['sku']),self.prepared)
            item=self.prepared['catalog_review','catalog-oct23-row-'+str(r['source_row'])]
            self.assertFalse(item['enabled']);self.assertTrue(item['publication_blocked']);self.assertTrue(item['question'])
        skus={s for (k,_),v in self.prepared.items() if k=='purchase_option' for s in v['skus']}
        self.assertFalse(skus.intersection(r['sku'] for r in held))
        view=CatalogView(self.prepared)
        bad=dict(id='bad-held',name='Bad held choice',therapy_id='hrt',duration_months=1,enabled=True,
                 skus=['EST-PATCH-0.05MG-BIW-1M'],payment_types=['once'])
        with self.assertRaises(Exception):view.prepare_plan('purchase_option',bad)

    def test_all_template_limits_and_distinct_variants(self):
        drafts=[v for (k,_),v in self.prepared.items() if k=='template_draft']
        self.assertEqual(len(drafts),26)
        for draft in drafts:
            for plan in draft['plans']:
                self.assertLessEqual(len(plan['skus']),20)
                self.assertEqual(len(plan['skus']),len(set(plan['skus'])))
        self.assertGreater(len(self.prepared['therapy','hrt']['treatments']),20)

    def test_atomic_idempotent_preserves_existing_prices(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'test.sqlite3'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE admin_config(kind TEXT,id TEXT,data TEXT,PRIMARY KEY(kind,id))')
                db.execute('INSERT INTO admin_config VALUES(?,?,?)',('brand','keep',json.dumps({'price':'88.00'})))
            with patch('socket.create_connection',side_effect=AssertionError('No provider access')):
                install(path,True)
                with sqlite3.connect(path) as db:
                    k=self.data['products'][0]['sku'];value=json.loads(db.execute("SELECT data FROM admin_config WHERE kind='master' AND id=?",(k,)).fetchone()[0])
                    value['offers'][0]['price']='123.00'
                    # Both members retain the editable pricing independently.
                    db.execute("UPDATE admin_config SET data=? WHERE kind='master' AND id=?",(json.dumps(value),k))
                self.assertTrue(install(path,True)['already_imported'])
            with sqlite3.connect(path) as db:
                self.assertEqual(json.loads(db.execute("SELECT data FROM admin_config WHERE kind='master' AND id=?",(k,)).fetchone()[0])['offers'][0]['price'],'123.00')
                self.assertEqual(json.loads(db.execute("SELECT data FROM admin_config WHERE kind='brand'").fetchone()[0]),{'price':'88.00'})

    def test_admin_review_requires_login_and_template_edit_works(self):
        from test_admin import AdminTests
        h=AdminTests();h.setUp()
        try:
            for (k,i),v in self.prepared.items():h.app.state.admin.put(k,i,v)
            response=h.client.get('/api/admin/catalog-review')
            self.assertEqual(response.status_code,200)
            self.assertEqual(len(response.json()['items']),788)
            draft=self.prepared['template_draft','master-therapy-biest-gel']
            review=h.review('template_editor',draft)
            self.assertFalse(review['preview']['stickyWrites'])
            self.assertEqual(h.apply(review).status_code,200)
            h.client.cookies.clear()
            self.assertEqual(h.client.get('/api/admin/catalog-review').status_code,401)
            self.assertFalse(h.fake.calls)
        finally:h.tearDown()

    def test_existing_therapy_and_sku_collision_are_not_overwritten(self):
        existing={('therapy','hrt'):{'id':'hrt','name':'HRT','enabled':True,'revision':3,'treatments':[{'id':'keep-existing','name':'Keep existing'}]}}
        prepared=prepare(existing)
        self.assertIn({'id':'keep-existing','name':'Keep existing'},prepared['therapy','hrt']['treatments'])
        sku=self.data['products'][0]['sku'];existing['master',sku]=self.prepared['master',sku]
        with self.assertRaises(Exception):prepare(existing)


if __name__=='__main__':unittest.main()
