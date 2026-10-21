"""Master assignment financial boundaries; all writes use a fake service."""
import copy
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from app import Settings,create_app
from test_checkout import ORIGIN
import test_admin as helpers
from qa.fake_master import MasterSticky

class MasterTests(unittest.TestCase):
    post=helpers.AdminTests.post
    review=helpers.AdminTests.review
    apply=helpers.AdminTests.apply
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.fake=MasterSticky()
        self.app=create_app(Settings(public_url=ORIGIN,state_dir=Path(self.temp.name),authorization_verified=True),self.fake)
        self.client=TestClient(self.app,base_url=ORIGIN);self.client.get('/admin?setup='+self.app.state.admin.setup_token)
        csrf=self.client.get('/api/admin/auth').json()['csrfToken']
        r=self.client.post('/api/admin/setup',headers={'Origin':ORIGIN,'X-CSRF-Token':csrf},json={'email':'master-owner@example.com','password':'synthetic-owner-password-123'})
        self.headers={'Origin':ORIGIN,'X-CSRF-Token':r.json()['csrfToken']}
    def tearDown(self):self.client.close();self.temp.cleanup()
    def preset(self):return self.client.get('/api/admin/master-preset').json()
    def seed(self):
        self.assertEqual(self.apply(self.review('master',self.preset())).status_code,200)
        self.assertEqual(self.apply(self.review('brand',{'id':'test-brand','name':'Test brand','campaign_id':422})).status_code,200)
    def provision(self,brand='test-brand'):
        r=self.review('provision',{'brand_id':brand});a=self.apply(r);self.assertEqual(a.status_code,200,a.text);return a.json()
    def state(self):return self.client.get('/api/admin/state').json()
    def test_master_preview_and_save_are_local_only_and_all_intervals_are_explicit(self):
        p=self.preset();self.assertEqual(p['offers'][0]['billing_models'],[3,4,5,7,6]);self.assertEqual(p['offers'][0]['price'],'449.00')
        r=self.review('master',p);self.assertEqual(self.state()['masters'],[])
        self.assertEqual(self.apply(r).status_code,200);self.assertEqual(self.state()['masters'][0]['revision'],1)
        self.assertEqual(self.state()['skus'][0]['sku'],'TIRZ-1M');self.assertFalse(self.fake.calls)
    def test_unknown_duplicate_models_and_mismatched_sku_are_rejected_before_writes(self):
        p=self.preset()
        for mids in ([3,3],[999]):
            d=copy.deepcopy(p);d['offers'][0]['billing_models']=mids
            self.assertEqual(self.post('reviews',{'kind':'master','data':d}).status_code,422)
        self.assertEqual(self.post('reviews',{'kind':'master','data':p|{'sku':'OTHER'}}).status_code,422)
        self.assertFalse(self.fake.calls)
    def test_assignment_creates_one_offer_all_models_and_a_private_payable_link(self):
        self.seed();r=self.review('provision',{'brand_id':'test-brand'})
        self.assertEqual(len(r['preview']['stickyWrites']),3);self.assertEqual(self.fake.count('/products'),0)
        a=self.apply(r);self.assertEqual(a.status_code,200,a.text);data=a.json();self.assertTrue(data['validation']['ready'])
        state=self.state();self.assertEqual(len(state['assignments']),1);link=state['links'][0]
        self.assertEqual(link['visibility'],'private');self.assertTrue(link['enabled']);self.assertEqual(len(link['options']),5)
        customer=TestClient(self.app,base_url=ORIGIN);self.assertEqual(customer.get('/c/'+link['id']).status_code,401)
        customer.get(link['url']);cfg=customer.get('/api/config',params={'link_id':link['id']}).json()
        self.assertEqual({o['days'] for o in cfg['options']},{30,90,180,270,360})
        self.assertEqual({o['basePrice'] for o in cfg['options']},{'449.0'})
        self.assertEqual(self.fake.campaign_offers[422][0],706)
        self.assertEqual(self.fake.count('/new_order'),0);self.assertEqual(self.fake.count('/authorize_payment'),0)
    def test_apply_replay_and_fresh_provisioning_do_not_duplicate_objects(self):
        self.seed();r=self.review('provision',{'brand_id':'test-brand'});a=self.apply(r).json();self.assertEqual(self.apply(r).json(),a)
        link_before=self.state()['links'][0];r2=self.review('provision',{'brand_id':'test-brand'})
        self.assertEqual(r2['preview']['stickyWrites'],[]);self.assertEqual(self.apply(r2).status_code,200)
        self.assertEqual(self.fake.count('/products'),1);self.assertEqual(self.fake.count('/offers'),1);self.assertEqual(self.state()['links'][0],link_before)
    def test_brand_price_edit_is_preserved_and_other_brand_has_its_own_price(self):
        self.seed();self.provision();old=self.state()['offers'][0]
        edit={k:old[k] for k in ('id','brand_id','sku','name','billing_models','configuration')};edit['price']='123.00'
        self.assertEqual(self.apply(self.review('offer',edit)).status_code,200)
        self.provision();first=next(o for o in self.state()['offers'] if o['brand_id']=='test-brand');self.assertEqual(first['price'],'123.00')
        self.apply(self.review('brand',{'id':'other-brand','name':'Other','campaign_id':167}));self.provision('other-brand')
        other=next(o for o in self.state()['offers'] if o['brand_id']=='other-brand');self.assertEqual(other['price'],'449.00');self.assertNotEqual(first['product_id'],other['product_id'])
        self.assertNotIn(other['offer_id'],self.fake.campaign_offers[422])
    def test_master_revision_does_not_silently_update_campaign_or_existing_price(self):
        self.seed();self.provision();link=self.state()['links'][0]
        preset=self.preset();preset['offers'][0]['price']='555.00';self.apply(self.review('master',preset))
        self.assertEqual(self.state()['links'][0],link)
        validation=self.post('master-validation',{'brand_id':'test-brand'}).json();self.assertFalse(validation['skus'][0]['masterCurrent'])
        self.provision();self.assertEqual(self.fake.count('/products'),1);self.assertEqual(self.state()['offers'][0]['price'],'449.00')
        self.assertEqual(self.state()['assignments'][0]['master_revision'],2)
    def test_model_or_master_change_invalidates_old_preview(self):
        self.seed();r=self.review('provision',{'brand_id':'test-brand'});self.fake.model_changes[3]={'days':31}
        self.assertEqual(self.apply(r).status_code,409);self.assertEqual(self.fake.count('/products'),0)
        self.fake.model_changes={};r=self.review('provision',{'brand_id':'test-brand'});self.apply(self.review('master',self.preset()))
        self.assertEqual(self.apply(r).status_code,409)
    def test_open_payment_blocks_provisioning_before_any_write(self):
        self.seed();r=self.review('provision',{'brand_id':'test-brand'});key=self.app.state.store.create(422,'TIRZ-1M');self.app.state.store.claim('new','awaiting_card',key)
        self.assertEqual(self.apply(r).status_code,409);self.assertEqual(self.fake.count('/products'),0)
    def test_uncertain_write_retains_ids_and_blocks_new_assignment_previews(self):
        self.seed();r=self.review('provision',{'brand_id':'test-brand'});self.fake.fail_offer=True
        self.assertEqual(self.apply(r).status_code,502);self.assertEqual(self.apply(r).status_code,409)
        self.assertIn('product_0_0',self.state()['reviews'][0]['result']['created'])
        self.assertEqual(self.post('reviews',{'kind':'provision','data':{'brand_id':'test-brand'}}).status_code,409)
        self.assertEqual(self.fake.count('/products'),1)
    def test_external_product_drift_is_blocked_instead_of_duplicated(self):
        self.seed();self.provision();product=self.state()['offers'][0]['product_id'];self.fake.products[product]['price']=99
        self.assertEqual(self.post('reviews',{'kind':'provision','data':{'brand_id':'test-brand'}}).status_code,409)
        self.assertEqual(self.fake.count('/products'),1)
    def test_quotes_validate_every_assigned_model_without_payment(self):
        self.seed();self.provision();r=self.post('master-validation',{'brand_id':'test-brand','location':{'country':'US','region':'CA','postal_code':'94105','shipping_id':2}})
        self.assertEqual(r.status_code,200,r.text);result=r.json();self.assertTrue(result['ready']);self.assertEqual(len(result['skus'][0]['checks']),5)
        self.assertTrue(all(c['quote_total']=='449.0' for c in result['skus'][0]['checks']))
        self.assertEqual(self.fake.count('/calculate'),0) # Fake handles quote responses without recording payment calls.
        self.assertEqual(self.fake.count('/authorize_payment'),0);self.assertEqual(self.fake.count('/new_order'),0)
    def test_private_link_visibility_and_disabled_state_survive_reassignment(self):
        self.seed();self.provision();link=self.state()['links'][0]
        data={k:link[k] for k in ('id','brand_id','sku','title','visibility','options','enabled')};data.update(enabled=False,visibility='public')
        self.apply(self.review('link',data));self.provision();after=self.state()['links'][0]
        self.assertFalse(after['enabled']);self.assertEqual(after['visibility'],'public')
    def test_removed_model_requires_explicit_link_adjustment(self):
        self.seed();self.provision();p=self.preset();p['offers'][0]['billing_models']=[3];self.apply(self.review('master',p))
        self.assertEqual(self.post('reviews',{'kind':'provision','data':{'brand_id':'test-brand'}}).status_code,422)
        self.assertEqual(self.fake.count('/products'),1)
    def test_saved_master_detects_later_schedule_drift(self):
        self.seed();self.fake.model_changes[3]={'days':31}
        self.assertEqual(self.post('reviews',{'kind':'provision','data':{'brand_id':'test-brand'}}).status_code,409)
        self.assertEqual(self.fake.count('/products'),0)
    def test_assigned_schedule_drift_is_not_reported_ready(self):
        self.seed();self.provision();self.fake.model_changes[3]={'days':31}
        result=self.post('master-validation',{'brand_id':'test-brand'}).json()
        self.assertFalse(result['ready']);self.assertIn('Billing terms changed',result['skus'][0]['checks'][0]['detail'])
    def test_master_source_change_requires_replacement_without_altering_prior_product(self):
        self.seed();self.provision();old=self.state()['offers'][0]['product_id']
        # A different source record for the same SKU is an explicit master revision.
        self.fake.products[59999]=self.fake.detail('/api/v2/products/2856')|{'id':59999,'is_shippable':0}
        p=self.preset();p['product_id']=59999;self.apply(self.review('master',p));self.provision()
        self.assertEqual(self.fake.count('/products'),2);self.assertTrue(self.fake.products[old]['is_shippable'])
        self.assertNotEqual(self.state()['offers'][0]['product_id'],old)
    def test_multiple_skus_and_offer_prices_resolve_their_own_references(self):
        self.seed();p=self.preset();p['offers'].append({'id':'once','name':'One-time','price':'199.00','billing_models':[2]})
        self.apply(self.review('master',p));other=self.preset();other.update(sku='SECOND-SKU',name='Second master',product_id=59999)
        self.fake.products[59999]=self.fake.detail('/api/v2/products/2856')|{'id':59999,'sku':'SECOND-SKU'}
        self.apply(self.review('master',other));r=self.provision();self.assertTrue(r['validation']['ready'])
        self.assertEqual(self.fake.count('/products'),3);self.assertEqual(len(self.state()['assignments']),2)
        self.assertEqual({o['price'] for o in self.state()['offers']},{'449.00','199.00'})
        self.provision();self.assertEqual(self.fake.count('/products'),3)
    def test_external_shipping_change_is_reported_and_not_silently_reused(self):
        self.seed();self.provision();pid=self.state()['offers'][0]['product_id'];self.fake.products[pid]['is_shippable']=0
        self.assertFalse(self.post('master-validation',{'brand_id':'test-brand'}).json()['ready'])
        self.assertEqual(self.post('reviews',{'kind':'provision','data':{'brand_id':'test-brand'}}).status_code,409)
    def test_currency_mismatch_is_rejected(self):
        self.seed();p=self.preset();p['currency']='EUR';self.apply(self.review('master',p))
        self.assertEqual(self.post('reviews',{'kind':'provision','data':{'brand_id':'test-brand'}}).status_code,422)
        self.assertEqual(self.fake.count('/products'),0)
    def test_master_routes_require_owner_and_csrf(self):
        outsider=TestClient(self.app,base_url=ORIGIN)
        self.assertEqual(outsider.get('/api/admin/master-preset').status_code,401)
        self.assertEqual(outsider.post('/api/admin/master-validation',json={'brand_id':'test-brand'}).status_code,401)
        self.assertEqual(self.client.post('/api/admin/master-validation',json={'brand_id':'test-brand'}).status_code,403)

    def test_new_local_sku_needs_no_existing_matching_product(self):
        p=self.preset();p.update(sku='NEW-MED',name='New medication',product_id=None)
        r=self.review('master',p);self.assertEqual(r['preview']['stickyWrites'],[])
        self.assertEqual(self.apply(r).status_code,200)
        master=self.state()['masters'][0];self.assertIsNone(master['product_id']);self.assertEqual(master['product_template']['sku'],'NEW-MED')
        r=self.review('campaign_setup',{'campaign_id':422});self.assertEqual(self.state()['brands'],[])
        self.assertEqual(self.apply(r).status_code,200);self.assertEqual(len(self.state()['brands']),1)
        self.assertTrue(self.state()['links'][0]['enabled']);self.assertEqual(self.state()['offers'][0]['sku'],'NEW-MED')
        old=self.state()['offers'][0];edit={k:old[k] for k in ('id','brand_id','sku','name','billing_models','configuration')};edit['price']='123.00'
        self.assertEqual(self.apply(self.review('offer',edit)).status_code,200)
    def test_direct_existing_campaign_assigns_all_and_reuses_brand_and_objects(self):
        self.apply(self.review('master',self.preset()))
        r=self.review('campaign_setup',{'campaign_id':422});self.assertEqual(len(r['preview']['entries']),1)
        a=self.apply(r);self.assertEqual(a.status_code,200,a.text);self.assertTrue(a.json()['validation']['ready'])
        self.assertEqual(self.apply(r).json(),a.json())
        r=self.review('campaign_setup',{'campaign_id':422});self.assertEqual(r['preview']['stickyWrites'],[])
        self.assertEqual(self.apply(r).status_code,200);self.assertEqual(len(self.state()['brands']),1);self.assertEqual(self.fake.count('/products'),1)
    def test_create_campaign_assigns_master_and_links_in_single_approval(self):
        self.apply(self.review('master',self.preset()))
        r=self.review('campaign_setup',{'name':'New brand','template_id':422})
        writes=r['preview']['stickyWrites'];self.assertEqual(len(writes),3);self.assertEqual(writes[-1]['path'],'/api/v2/campaigns')
        self.assertFalse(self.fake.calls);a=self.apply(r);self.assertEqual(a.status_code,200,a.text)
        cid=a.json()['created']['campaign'];self.assertEqual(self.state()['brands'][0]['campaign_id'],cid)
        self.assertTrue(a.json()['validation']['ready']);self.assertEqual(self.state()['assignments'][0]['campaign_id'],cid)
        again=self.review('campaign_setup',{'campaign_id':cid});self.assertEqual(again['preview']['stickyWrites'],[])
        self.assertEqual(self.apply(again).status_code,200);self.assertEqual(self.fake.count('/campaigns'),1)
    def test_creation_access_failure_records_ids_and_blocks_duplicate(self):
        self.apply(self.review('master',self.preset()));r=self.review('campaign_setup',{'name':'New brand','template_id':422})
        self.fake.deny_new_campaign=True;self.assertEqual(self.apply(r).status_code,502)
        saved=self.state()['reviews'][0];self.assertEqual(saved['status'],'reconcile');self.assertIn('campaign',saved['result']['created'])
        self.assertEqual(self.state()['brands'],[]);self.assertEqual(self.post('reviews',{'kind':'campaign_setup','data':{'name':'New brand','template_id':422}}).status_code,409)
        self.assertEqual(self.fake.count('/campaigns'),1)
        cid=saved['result']['created']['campaign'];self.fake.deny_new_campaign=False
        self.assertEqual(self.post('reviews',{'kind':'campaign_setup','data':{'campaign_id':cid}}).status_code,409)
    def test_direct_assignment_blocks_open_payment_without_existing_brand(self):
        self.apply(self.review('master',self.preset()));r=self.review('campaign_setup',{'campaign_id':422})
        key=self.app.state.store.create(422,'TIRZ-1M');self.app.state.store.claim('new','awaiting_card',key)
        self.assertEqual(self.apply(r).status_code,409);self.assertFalse(self.fake.calls)
    def test_uncertain_direct_assignment_cannot_be_bypassed_with_old_provision_route(self):
        self.seed();r=self.review('campaign_setup',{'campaign_id':422});self.fake.fail_offer=True
        self.assertEqual(self.apply(r).status_code,502)
        self.assertEqual(self.post('reviews',{'kind':'provision','data':{'brand_id':'test-brand'}}).status_code,409)
        self.assertEqual(self.post('reviews',{'kind':'campaign_setup','data':{'campaign_id':422}}).status_code,409)
    def test_setup_requires_master_and_checks_template_changes_before_writes(self):
        self.assertEqual(self.post('reviews',{'kind':'campaign_setup','data':{'campaign_id':422}}).status_code,422)
        self.apply(self.review('master',self.preset()));r=self.review('campaign_setup',{'name':'New brand','template_id':422})
        self.fake.link_gateway=999;self.assertEqual(self.apply(r).status_code,409);self.assertFalse(self.fake.calls)
    def test_setup_never_exposes_gateway_credentials(self):
        self.apply(self.review('master',self.preset()));r=self.review('campaign_setup',{'name':'New brand','template_id':422})
        self.assertNotIn('NEVER_EXPOSE_THIS',str(r));self.assertNotIn('access_token',str(r))

    def test_local_fulfillment_preserves_weight_and_price_revision_reuses_brand_offer(self):
        self.fake.products[59999]=self.fake.detail('/api/v2/products/2856')|{'id':59999,'weight':'1.5','weight_unit':{'id':2},'description':'Original medication description'}
        p=self.preset()|{'sku':'LOCAL-MED','name':'Local medication','product_id':None,'fulfillment_product_id':59999}
        self.apply(self.review('master',p));r=self.apply(self.review('campaign_setup',{'campaign_id':422}))
        self.assertEqual(r.status_code,200,r.text);self.assertTrue(r.json()['validation']['ready'])
        product=self.fake.products[self.state()['offers'][0]['product_id']]
        self.assertEqual(product['weight_unit_id'],2);self.assertEqual(product['description'],'Local medication')
        p['offers'][0]['price']='555.00';self.apply(self.review('master',p))
        r=self.review('campaign_setup',{'campaign_id':422});self.assertEqual(r['preview']['stickyWrites'],[])
        self.assertEqual(self.apply(r).status_code,200);self.assertEqual(self.state()['offers'][0]['price'],'449.00')

if __name__=='__main__':unittest.main()
