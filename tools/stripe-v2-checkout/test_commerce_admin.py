"""Brand commerce boundaries, provider uncertainty and public price propagation."""
import copy
import json
import unittest
from datetime import date, timedelta
from fastapi.testclient import TestClient
import test_admin as admin_tests
from test_checkout import ORIGIN, SKU
from demo.runtime import PricedManifest


class CouponSticky(admin_tests.AdminSticky):
    def __init__(self):
        super().__init__()
        self.coupons={};self.coupon_assignments={};self.fail_coupon=False;self.fail_assignment=False;self.mismatch=False

    def detail(self,path):
        if path.startswith('/api/v2/coupons/'):
            return copy.deepcopy(self.coupons[int(path.rsplit('/',1)[1])])
        result=super().detail(path)
        if path.startswith('/api/v2/campaigns/'):
            cid=int(path.rsplit('/',1)[1])
            result['coupon_profiles']=[{'id':i,'name':self.coupons[i]['name']} for i in self.coupon_assignments.get(cid,[])]
        return result

    def call(self,method,path,body=None):
        if method=='POST' and path=='/api/v2/coupons':
            self.calls.append((method,path,copy.deepcopy(body)))
            if self.fail_coupon:raise RuntimeError('Uncertain write')
            cid=3000+len(self.coupons)
            self.coupons[cid]={'id':cid,'name':body['name'],'type_id':1,'is_active':1,
                'discount_percent':body['discount']['percent'], 'is_lifetime':body['is_lifetime'],
                'is_free_shipping':0,'limits':body['limits'],
                'expires_at':{'date':body['expiration']['date']+' 00:00:00','timezone':body['expiration']['timezone']},
                'promo_codes':[{'code':body['promo_codes'][0]['code'],'is_active':1,'is_deleted':0}],
                'creator':{'password':'must-not-leak'}}
            if self.mismatch:self.coupons[cid]['is_lifetime']=1-body['is_lifetime']
            return {'status':'SUCCESS','data':{'id':cid}}
        if method=='PUT' and '/coupon-profiles/' in path:
            self.calls.append((method,path,copy.deepcopy(body)))
            if self.fail_assignment:raise RuntimeError('Uncertain attachment')
            cid,pid=map(int,(path.split('/')[4],path.split('/')[-1]))
            self.coupon_assignments.setdefault(cid,[]).append(pid)
            return {'status':'SUCCESS'}
        return super().call(method,path,body)


class CommerceTests(unittest.TestCase):
    setUp=admin_tests.AdminTests.setUp
    tearDown=admin_tests.AdminTests.tearDown
    post=admin_tests.AdminTests.post
    review=admin_tests.AdminTests.review
    apply=admin_tests.AdminTests.apply
    seed=admin_tests.AdminTests.seed
    link_data=admin_tests.AdminTests.link_data

    def setup_commerce(self):
        self.seed();fake=CouponSticky();self.fake=fake;self.app.state.admin.api=fake
        self.app.state.admin.put('brand','second-brand',{'id':'second-brand','name':'Second','campaign_id':423})
        return fake

    def coupon(self,**changes):
        return {'campaign_id':422,'code':'SAVE10','percent':10,'applies_to_renewals':False,
                'expires_on':str(date.today()+timedelta(days=14)), 'timezone':'America/New_York',
                'max_uses':100,'max_uses_per_customer':2,**changes}

    def coupon_review(self,**changes):
        return self.post('brands/test-brand/coupons/reviews',self.coupon(**changes))

    def offer(self):
        r=self.review('offer',{'brand_id':'test-brand','sku':SKU,'name':'One time','price':'3.00','billing_models':[2]})
        self.assertEqual(self.apply(r).status_code,200)
        return self.app.state.admin.records('offering')[0]

    def test_owner_and_csrf_required(self):
        outsider=TestClient(self.app,base_url=ORIGIN)
        for path in ['brands/test-brand/prices','brands/test-brand/coupons?campaign_id=422']:
            self.assertEqual(outsider.get('/api/admin/'+path).status_code,401)
        self.assertEqual(outsider.post('/api/admin/brands/test-brand/coupons/reviews',json=self.coupon()).status_code,401)
        self.assertEqual(self.client.post('/api/admin/brands/test-brand/coupons/reviews',json=self.coupon()).status_code,403)

    def test_brand_openapi_is_private_and_has_no_public_management_endpoints(self):
        self.setup_commerce()
        path='/api/admin/brands/test-brand/commerce/openapi.json'
        outsider=TestClient(self.app,base_url=ORIGIN)
        self.assertEqual(outsider.get(path).status_code,401)
        r=self.client.get(path);self.assertEqual(r.status_code,200,r.text)
        schema=r.json();self.assertIn('/api/admin/brands/test-brand/coupons/reviews',schema['paths'])
        self.assertNotIn('/api/admin/login',schema['paths'])
        security=schema['paths']['/api/admin/brands/test-brand/coupons/reviews']['post']['security']
        self.assertEqual(security,[{'adminSession':[],'csrfToken':[]}])

    def test_create_readback_assign_and_idempotent_apply(self):
        fake=self.setup_commerce()
        r=self.coupon_review();self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(len(fake.coupons),0)
        self.assertEqual(self.apply(r.json()).status_code,200)
        self.assertEqual(self.apply(r.json()).status_code,200)
        self.assertEqual(len(fake.coupons),1)
        self.assertEqual(fake.coupon_assignments,{422:[3000]})
        result=self.client.get('/api/admin/brands/test-brand/coupons?campaign_id=422')
        self.assertEqual(result.json()['coupons'][0]['codes'],['SAVE10'])
        self.assertNotIn('must-not-leak',result.text)
        self.assertEqual(self.coupon_review().status_code,409)
        self.assertEqual(self.client.get('/api/admin/brands/second-brand/coupons?campaign_id=423').json()['coupons'],[])

    def test_new_coupon_preserves_existing_and_renewal_choice(self):
        fake=self.setup_commerce();r=self.coupon_review().json();self.apply(r)
        r=self.coupon_review(code='RENEW20',percent=20,applies_to_renewals=True)
        self.assertEqual(self.apply(r.json()).status_code,200)
        self.assertEqual(fake.coupon_assignments[422],[3000,3001])
        self.assertEqual(fake.coupons[3001]['is_lifetime'],1)

    def test_cross_brand_and_shared_campaign_blocked(self):
        self.setup_commerce()
        self.assertEqual(self.coupon_review(campaign_id=423).status_code,404)
        self.app.state.admin.put('brand','shared',{'id':'shared','name':'Shared','campaign_id':422})
        self.assertEqual(self.coupon_review().status_code,409)

    def test_validation(self):
        self.setup_commerce()
        for changes in [{'percent':100},{'percent':0},{'percent':10.5},{'expires_on':str(date.today())},
                        {'timezone':'wrong/timezone'},{'max_uses':0},{'code':'<script>'},{'discount_amount':1}]:
            with self.subTest(changes=changes):self.assertEqual(self.coupon_review(**changes).status_code,422)

    def test_uncertain_creation_no_retry(self):
        fake=self.setup_commerce();fake.fail_coupon=True;r=self.coupon_review().json()
        self.assertEqual(self.apply(r).status_code,502)
        self.assertEqual(self.apply(r).status_code,409)
        self.assertEqual(self.coupon_review(code='OTHER').status_code,409)
        self.assertEqual(sum(p=='/api/v2/coupons' for _,p,_ in fake.calls),1)

    def test_failed_attachment_retains_created_id(self):
        fake=self.setup_commerce();fake.fail_assignment=True;r=self.coupon_review().json()
        self.assertEqual(self.apply(r).status_code,502)
        with self.app.state.admin.store.db() as db:
            row=db.execute('SELECT status,result FROM admin_reviews WHERE id=?',(r['id'],)).fetchone()
        self.assertEqual(row[0],'reconcile');self.assertEqual(json.loads(row[1])['created']['coupon'],3000)
        self.assertEqual(self.apply(r).status_code,409)

    def test_mismatched_readback_does_not_attach(self):
        fake=self.setup_commerce();fake.mismatch=True;r=self.coupon_review().json()
        self.assertEqual(self.apply(r).status_code,502);self.assertEqual(fake.coupon_assignments,{})

    def test_stale_provider_configuration_blocked(self):
        fake=self.setup_commerce();r=self.coupon_review().json()
        fake.coupon_assignments[422]=[999];fake.coupons[999]={'name':'External change'}
        self.assertEqual(self.apply(r).status_code,409)
        self.assertFalse(any(p=='/api/v2/coupons' for _,p,_ in fake.calls))

    def test_coupon_changes_do_not_interrupt_open_payments(self):
        fake=self.setup_commerce();r=self.coupon_review().json();store=self.app.state.admin.store
        key=store.create(422,SKU)
        with store.db() as db:db.execute("UPDATE checkouts SET status='awaiting_card' WHERE id=?",(key,))
        self.assertEqual(self.apply(r).status_code,409)
        self.assertEqual(fake.coupons,{})

    def test_price_changes_are_brand_scoped_and_preserve_original_objects(self):
        fake=self.setup_commerce();old=self.offer();admin=self.app.state.admin
        other=copy.deepcopy(old)|{'id':'second-offer','brand_id':'second-brand','campaign_id':423}
        admin.put('offering',other['id'],other)
        link=self.link_data();link['options']=[f"{old['offer_id']}:{old['product_id']}:2"]
        admin.put('link',link['id'],link)
        path='brands/test-brand/prices/'+old['id']+'/reviews'
        r=self.post(path,{'price':'5.00','expected_price':'3.00'})
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(self.apply(r.json()).status_code,200)
        changed=admin.get('offering',old['id'])
        self.assertEqual(changed['price'],'5.00');self.assertNotEqual(changed['product_id'],old['product_id'])
        self.assertEqual(float(fake.products[old['product_id']]['price']),3.00)
        self.assertEqual(admin.get('offering','second-offer'),other)
        self.assertEqual(admin.get('link',link['id'])['options'],[f"{changed['offer_id']}:{changed['product_id']}:2"])
        self.assertEqual(self.post(path,{'price':'6.00','expected_price':'3.00'}).status_code,409)
        self.assertEqual(self.post('brands/second-brand/prices/'+old['id']+'/reviews',{'price':'6.00','expected_price':'5.00'}).status_code,404)
        rows=self.client.get('/api/admin/brands/second-brand/prices').json()['prices']
        self.assertEqual([p['id'] for p in rows],['second-offer'])

    def test_publication_follows_only_approved_same_brand_replacements(self):
        self.setup_commerce();admin=self.app.state.admin
        source={'sites':[{'brand_id':'test-brand','campaign_id':422,'therapies':[{'plans':[{'selection':'7:6:2'}]}]},
                         {'brand_id':'second-brand','campaign_id':423,'therapies':[{'plans':[{'selection':'7:6:2'}]}]}]}
        manifest=PricedManifest(lambda:source,admin);original=manifest()
        admin.put('price_replacement','one',{'brand_id':'test-brand','campaign_id':422,'old_offer':7,'old_product':6,'offer':9,'product':8,'billing_models':[2]})
        result=manifest();self.assertIsNot(original,result);self.assertIs(result,manifest())
        self.assertEqual(result['sites'][0]['therapies'][0]['plans'][0]['selection'],'9:8:2')
        self.assertEqual(result['sites'][1]['therapies'][0]['plans'][0]['selection'],'7:6:2')
        self.assertEqual(source['sites'][0]['therapies'][0]['plans'][0]['selection'],'7:6:2')
        admin.put('price_replacement','two',{'brand_id':'test-brand','campaign_id':422,'old_offer':9,'old_product':8,'offer':11,'product':10,'billing_models':[2]})
        self.assertEqual(manifest()['sites'][0]['therapies'][0]['plans'][0]['selection'],'11:10:2')

    def test_synthetic_staging_can_create_and_persist_coupons_without_network(self):
        from synthetic import SyntheticSticky
        self.seed();fake=SyntheticSticky(self.temp.name);self.app.state.admin.api=fake
        r=self.coupon_review().json();self.assertEqual(self.apply(r).status_code,200)
        restored=SyntheticSticky(self.temp.name)
        self.assertEqual(restored.detail('/api/v2/campaigns/422')['coupon_profiles'][0]['name'],'SAVE10')
        with self.assertRaises(RuntimeError):restored.call('POST','/api/v1/new_order',{})
