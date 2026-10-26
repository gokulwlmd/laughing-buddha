import json
import sqlite3
import unittest
from test_astv_masters import ASTVMasterTests
from import_astv_masters import install as initial_install, prepare as initial_prepare
from update_astv_refills import install, prepare
from member_portal.intake_templates import get_template, binding_for_sku
from catalog_refill_policies import astv_source_products


class ASTVRefillTests(ASTVMasterTests):
    def test_sheet_only_selection_and_intake(self):
        initial_install(self.path,True)
        before=self.rows()
        self.assertFalse(install(self.path)['applied'])
        self.assertEqual(before,self.rows())
        install(self.path,True)
        rows=self.rows()
        for months in (1,3,6,12):
            for suffix in ('','-SUB'):
                sku=f'ASTV-5P-{months}M{suffix}'
                master=rows['master',sku]
                self.assertEqual(master['enabled'],months==1)
                self.assertEqual(master['product_setup']['shipment_count'],1 if months==1 else None)
                self.assertEqual(master['offers'],before['master',sku]['offers'])
                if months == 1:
                    policy=rows['refill_policy',sku]
                    self.assertFalse(policy['included_refills_enabled'])
                    self.assertFalse(policy['check_in_required'])
                    self.assertTrue(policy['initial_intake_required'])
                    self.assertTrue(get_template('erectile-dysfunction',sku=sku)['questions'])
                else:
                    self.assertNotIn(('refill_policy',sku),rows)
                    self.assertIsNone(binding_for_sku(sku))
                self.assertEqual(rows['purchase_option',f'astv-5pack-{months}m']['enabled'],months==1)
        self.assertEqual(len(rows['template_draft','master-therapy-astv-5pack']['plans']),1)
        self.assertTrue(install(self.path,True)['already_imported'])
        self.assertEqual(rows,self.rows())

    def test_delivery_update_rolls_back_and_rejects_changed_schedule(self):
        initial_install(self.path,True)
        before=self.rows()
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TRIGGER fail_policy BEFORE UPDATE ON admin_config WHEN NEW.id='ASTV-5P-12M-SUB' BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):install(self.path,True)
        self.assertEqual(before,self.rows())
        before['master','ASTV-5P-6M']['planning_contract']['shipments_per_term']=2
        with self.assertRaises(ValueError):prepare(before)

