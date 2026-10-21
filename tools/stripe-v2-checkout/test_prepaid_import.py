"""The authorized fixture import preserves owner data and is atomic/idempotent."""
import contextlib,io,unittest
import test_master as helpers
from import_prepaid_fixture import run
from prepaid import configuration

class ImportTests(unittest.TestCase):
    setUp=helpers.MasterTests.setUp
    tearDown=helpers.MasterTests.tearDown
    post=helpers.MasterTests.post
    review=helpers.MasterTests.review
    apply=helpers.MasterTests.apply
    def seed(self):
        self.apply(self.review('brand',{'id':'campaign-422','name':'Existing test brand','campaign_id':422}))
        self.fake.offers[712]={'id':712,'name':'Synthetic prepaid',**configuration(4),'products':[{'id':55098}],'billing_models':[{'id':4}]};self.fake.campaign_offers[422]=[706,712]
        with self.app.state.store.db() as db:db.execute("UPDATE checkouts SET status='captured',order_id='505015' WHERE id='legacy'")
    def test_import_adds_only_five_records_preserves_owner_and_reviews_and_replays_without_changes(self):
        self.seed();admin=self.app.state.admin
        with admin.store.db() as db:owner=db.execute('SELECT * FROM admin_owner').fetchall();reviews=db.execute('SELECT * FROM admin_reviews').fetchall()
        with contextlib.redirect_stdout(io.StringIO()):run(self.app)
        with admin.store.db() as db:
            before=db.execute('SELECT * FROM admin_config ORDER BY kind,id').fetchall();self.assertEqual(len(before),6);self.assertEqual(db.execute('SELECT * FROM admin_owner').fetchall(),owner);self.assertEqual(db.execute('SELECT * FROM admin_reviews').fetchall(),reviews);self.assertEqual(db.execute('SELECT count(*) FROM admin_setup_runs').fetchone()[0],1)
        self.assertFalse(admin.get('master','WLMD-PREPAY-cfef3de8')['enabled']);self.assertEqual(admin.records('link')[0]['visibility'],'private')
        with contextlib.redirect_stdout(io.StringIO()):run(self.app)
        with admin.store.db() as db:self.assertEqual(db.execute('SELECT * FROM admin_config ORDER BY kind,id').fetchall(),before)
        self.assertFalse(any(method in ('PUT','POST') and path!='/api/v2/order_total/calculate' for method,path,_ in self.fake.calls))
    def test_partial_collision_stops_without_overwriting_or_inserting_other_records(self):
        self.seed();admin=self.app.state.admin;admin.put('sku','WLMD-PREPAY-cfef3de8',{'sku':'WLMD-PREPAY-cfef3de8','name':'Owner existing choice','product_id':55098})
        with admin.store.db() as db:before=db.execute('SELECT * FROM admin_config ORDER BY kind,id').fetchall()
        with self.assertRaises(AssertionError):run(self.app)
        with admin.store.db() as db:self.assertEqual(db.execute('SELECT * FROM admin_config ORDER BY kind,id').fetchall(),before)
