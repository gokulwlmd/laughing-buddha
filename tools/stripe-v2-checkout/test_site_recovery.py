import copy
import json
import unittest
import test_sites as helpers
from master import product_contract_matches
from reconcile_site import recover


class SiteRecoveryTests(unittest.TestCase):
    setUp=helpers.SiteTests.setUp
    tearDown=helpers.SiteTests.tearDown
    post=helpers.SiteTests.post
    review=helpers.SiteTests.review
    apply=helpers.SiteTests.apply
    state=helpers.SiteTests.state
    preset=helpers.SiteTests.preset
    provision=helpers.SiteTests.provision
    save=helpers.SiteTests.save
    seed=helpers.SiteTests.seed

    def fresh_site(self):
        original=self.fake.detail
        self.fake.detail=lambda path:dict(original(path),is_shippable=0) if path=='/api/v2/products/2856' else original(path)
        self.seed()
        self.save('brand',{'id':'second-brand','name':'Second site','campaign_id':167})
        self.site.update(brand_id='second-brand',campaign_id=167)
        self.original_products=set(self.fake.products)
        self.seed_product_count=sum(p=='/api/v2/products' for _,p,_ in self.fake.calls)

    def defaults(self):
        original=self.fake.detail
        def detail(path):
            value=original(path)
            if '/products/' in path and int(path.rsplit('/',1)[1]) not in self.original_products and int(path.rsplit('/',1)[1]) in self.fake.products and not value.get('is_shippable'):
                value=dict(value,weight=0,weight_unit={'id':1})
            return value
        self.fake.detail=detail

    def partial(self):
        self.fresh_site();review=self.review('site',self.site);key=review['id']
        with self.app.state.store.db() as db:
            plan=json.loads(db.execute('SELECT data FROM admin_reviews WHERE id=?',(key,)).fetchone()[0])
        first=plan['operations'][0]
        created=self.fake.call(first['method'],first['path'],first['body'])['data']['id']
        self.defaults()
        with self.app.state.store.db() as db:
            db.execute("UPDATE admin_reviews SET status='reconcile',result=? WHERE id=?",(json.dumps({'status':'reconcile','created':{first['save']:created}}),key))
        return key,created

    def test_new_site_accepts_only_harmless_api_weight_defaults(self):
        self.fresh_site();self.defaults()
        result=self.apply(self.review('site',self.site))
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['checkouts'][0]['status'],'ready')

    def test_recovery_reuses_first_product_and_finishes_original_approved_plan(self):
        key,pid=self.partial();admin=self.app.state.admin;before=copy.deepcopy(self.fake.calls)
        inspected=recover(admin,key)
        self.assertFalse(inspected['applied']);self.assertEqual(self.fake.calls,before)
        result=recover(admin,key,apply=True)
        self.assertTrue(result['applied']);self.assertIn(pid,result['result']['created'].values())
        self.assertEqual(sum(p=='/api/v2/products' for _,p,_ in self.fake.calls)-self.seed_product_count,len(result['result']['created'])//2)
        self.assertEqual(self.fake.count('/authorize_payment'),0);self.assertEqual(self.fake.count('/new_order'),0)
        with self.assertRaises(ValueError):recover(admin,key,apply=True)

    def test_price_drift_and_open_payments_stop_recovery_before_any_write(self):
        key,pid=self.partial();original=self.fake.detail
        self.fake.detail=lambda path:dict(original(path),price='999.00') if path.endswith('/'+str(pid)) else original(path)
        before=copy.deepcopy(self.fake.calls)
        with self.assertRaises(ValueError):recover(self.app.state.admin,key,apply=True)
        self.assertEqual(self.fake.calls,before)
        self.fake.detail=original
        payment=self.app.state.store.create(167,'TIRZ-1M');self.app.state.store.claim('new','awaiting_card',payment)
        with self.assertRaises(ValueError):recover(self.app.state.admin,key,apply=True)
        self.assertEqual(self.fake.calls,before)

    def test_explicit_weights_shipping_tax_sku_and_units_remain_strict(self):
        source={'is_shippable':0,'weight':None,'weight_unit_id':None,'taxable':0,'sku':'EXAMPLE'}
        actual=dict(source,weight='0',weight_unit_id=1)
        self.assertTrue(product_contract_matches(source,actual))
        for changes in ({'taxable':1},{'is_shippable':1},{'weight':'1'},{'weight_unit_id':2},{'sku':'OTHER'}):
            self.assertFalse(product_contract_matches(source,actual|changes))
        self.assertFalse(product_contract_matches(source|{'is_shippable':1},actual|{'is_shippable':1}))
