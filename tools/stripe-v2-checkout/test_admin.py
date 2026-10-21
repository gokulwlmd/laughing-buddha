"""Owner-admin boundary tests use only fake Sticky data and synthetic credentials."""
import copy
from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from app import Settings,create_app
from test_checkout import FakeSticky,SKU,ORIGIN,CONTACT

class AdminSticky(FakeSticky):
    def __init__(self):
        super().__init__();self.products={};self.offers={};self.attached=[706];self.price='2.00';self.fail_offer=False
    def detail(self,path):
        if '/products/' in path:
            pid=int(path.rsplit('/',1)[1])
            if pid in self.products:return copy.deepcopy(self.products[pid])
            return super().detail(path)|{'price':self.price,'category_id':113,'cost_of_goods':'0','restocking_fee':'0','max_quantity':1}
        if '/offers/' in path:return copy.deepcopy(self.offers[int(path.rsplit('/',1)[1])])
        if '/campaigns/' in path:
            c=super().detail(path);c['id']=int(path.rsplit('/',1)[1]);c['offers']=[c['offers'][0]]+[copy.deepcopy(self.offers[i]) for i in self.attached if i!=706];return c
        return super().detail(path)
    def call(self,method,path,body=None):
        if path=='/api/v2/order_total/calculate' and body['offers'][0]['product_id'] in self.products:
            product=self.products[body['offers'][0]['product_id']]
            return {'status':'SUCCESS','data':{'total':str(product['price']),'line_items':[{'id':product['id'],'qty':1}]}}
        if path=='/api/v1/campaign_find_active':return {'response_code':'100','campaigns':{'422':{'campaign_id':'422','campaign_name':'Synthetic campaign'}}}
        if path=='/api/v2/billing_models':return {'status':'SUCCESS','data':[{'id':2,'name':'One time','is_archived':0}]}
        if method=='POST' and path=='/api/v2/products':
            self.calls.append((method,path,copy.deepcopy(body)));key=60000+len(self.products);self.products[key]=body|{'id':key,'archived_flag':0,'taxable':body['is_taxable']};return {'status':'SUCCESS','data':{'id':key}}
        if method=='POST' and path=='/api/v2/offers':
            self.calls.append((method,path,copy.deepcopy(body)))
            if self.fail_offer:raise RuntimeError('Simulated uncertain write')
            key=70000+len(self.offers);self.offers[key]=body|{'id':key};return {'status':'SUCCESS','data':{'id':key}}
        if method=='PUT' and '/campaigns/' in path:
            self.calls.append((method,path,copy.deepcopy(body)));self.attached=body['offers'];return {'status':'SUCCESS','data':{'id':422}}
        return super().call(method,path,body)

class AdminTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.fake=AdminSticky()
        self.cfg=Settings(public_url=ORIGIN,state_dir=Path(self.temp.name),authorization_verified=True)
        self.app=create_app(self.cfg,self.fake);self.client=TestClient(self.app,base_url=ORIGIN)
        self.client.get('/admin?setup='+self.app.state.admin.setup_token)
        csrf=self.client.get('/api/admin/auth').json()['csrfToken']
        r=self.client.post('/api/admin/setup',headers={'Origin':ORIGIN,'X-CSRF-Token':csrf},json={'email':'owner@example.com','password':'synthetic-owner-password-123'})
        self.assertEqual(r.status_code,200,r.text)
        self.headers={'Origin':ORIGIN,'X-CSRF-Token':r.json()['csrfToken']}
    def tearDown(self):self.client.close();self.temp.cleanup()
    def post(self,path,body):return self.client.post('/api/admin/'+path,headers=self.headers,json=body)
    def review(self,kind,data):
        r=self.post('reviews',{'kind':kind,'data':data});self.assertEqual(r.status_code,200,r.text);return r.json()
    def apply(self,r):return self.post('apply',{'review_id':r['id'],'approve':True})
    def seed(self):
        self.assertEqual(self.apply(self.review('brand',{'id':'test-brand','name':'Test Brand','campaign_id':422})).status_code,200)
        self.assertEqual(self.apply(self.review('sku',{'sku':SKU,'name':'Test SKU','product_id':54537})).status_code,200)
    def link_data(self,visibility='public',id='test-link'):
        return {'id':id,'brand_id':'test-brand','sku':SKU,'title':'Test checkout','visibility':visibility,'options':['706:54537:2']}
    def publish(self,visibility='public',id='test-link'):
        self.seed();r=self.review('link',self.link_data(visibility,id));a=self.apply(r);self.assertEqual(a.status_code,200,a.text)
        return self.client.get('/api/admin/state').json()['links'][0]
    def test_admin_page_is_real_login_and_data_requires_owner_session(self):
        outsider=TestClient(self.app,base_url=ORIGIN)
        self.assertEqual(outsider.get('/admin').status_code,200)
        self.assertEqual(outsider.get('/api/admin/state').status_code,401)
        outsider.cookies.set('checkout_access',self.app.state.invite)
        self.assertEqual(outsider.get('/api/admin/state').status_code,401)
    def test_setup_cannot_be_reused_and_password_is_hashed(self):
        self.assertEqual(self.client.get('/admin?setup='+self.app.state.admin.setup_token).status_code,200)
        outsider=TestClient(self.app,base_url=ORIGIN)
        outsider.get('/admin?setup='+self.app.state.admin.setup_token)
        self.assertEqual(outsider.get('/api/admin/state').status_code,401)
        raw=(Path(self.temp.name)/'checkout.sqlite3').read_bytes()
        self.assertNotIn(b'synthetic-owner-password-123',raw)
        self.assertNotIn(self.client.cookies.get('__Host-admin').encode(),raw)
    def test_login_logout_and_wrong_password(self):
        self.assertEqual(self.post('logout',{}).status_code,200)
        self.assertEqual(self.client.get('/api/admin/state').status_code,401)
        r=self.client.post('/api/admin/login',headers={'Origin':ORIGIN},json={'email':'owner@example.com','password':'wrong'})
        self.assertEqual(r.status_code,401)
        r=self.client.post('/api/admin/login',headers={'Origin':ORIGIN},json={'email':'owner@example.com','password':'synthetic-owner-password-123'})
        self.assertEqual(r.status_code,200);self.assertEqual(self.client.get('/api/admin/state').status_code,200)
    def test_cross_origin_and_missing_csrf_cannot_mutate(self):
        body={'kind':'brand','data':{'id':'brand-one','name':'Brand'}}
        self.assertEqual(self.client.post('/api/admin/reviews',json=body).status_code,403)
        self.assertEqual(self.client.post('/api/admin/reviews',headers=self.headers|{'Origin':'https://attacker.example'},json=body).status_code,403)
    def test_preview_is_read_only_until_approved_and_apply_is_idempotent(self):
        r=self.review('brand',{'id':'brand-one','name':'Brand'})
        self.assertEqual(self.client.get('/api/admin/state').json()['brands'],[])
        self.assertEqual(self.post('apply',{'review_id':r['id'],'approve':False}).status_code,422)
        self.assertEqual(self.apply(r).status_code,200);self.assertEqual(self.apply(r).status_code,200)
        self.assertEqual(len(self.client.get('/api/admin/state').json()['brands']),1)
        self.assertFalse(self.fake.calls)
    def test_stale_preview_requires_new_review(self):
        r=self.review('brand',{'id':'brand-one','name':'First'})
        self.apply(self.review('brand',{'id':'brand-two','name':'Second'}))
        self.assertEqual(self.apply(r).status_code,409)
    def test_exact_sku_and_invalid_link_option_are_checked(self):
        self.seed()
        self.assertEqual(self.post('reviews',{'kind':'sku','data':{'sku':'WRONG','name':'Wrong','product_id':54537}}).status_code,422)
        self.assertEqual(self.post('reviews',{'kind':'link','data':self.link_data()|{'options':['999:1:2']}}).status_code,422)
    def test_public_link_has_its_own_checkout_scope_and_branding(self):
        self.publish()
        customer=TestClient(self.app,base_url=ORIGIN);self.assertEqual(customer.get('/c/test-link').status_code,200)
        c=customer.get('/api/config',params={'link_id':'test-link','campaign_id':999,'sku':'WRONG'}).json()
        self.assertEqual(c['campaignId'],422);self.assertEqual(c['sku'],SKU);self.assertEqual(c['branding']['name'],'Test Brand')
        self.assertEqual(len(c['options']),1)
        self.assertEqual(customer.get('/api/config').status_code,401)
        s=customer.get('/api/status',params={'link_id':'test-link'}).json()
        headers={'Origin':ORIGIN,'X-CSRF-Token':c['csrfToken'],'X-Checkout-Attempt':s['attemptId']}
        r=customer.post('/api/quote',params={'link_id':'test-link'},headers=headers,json={'contact':CONTACT,'selection':'706:54537:2','shipping_id':2})
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['amount'],200)
    def test_private_link_requires_its_specific_invitation(self):
        l=self.publish('private');customer=TestClient(self.app,base_url=ORIGIN)
        self.assertEqual(customer.get('/c/test-link').status_code,401)
        self.assertEqual(customer.get('/c/test-link?access=wrong').status_code,401)
        self.assertEqual(customer.get(l['url'].replace(ORIGIN,'')).status_code,200)
        self.assertEqual(customer.get('/api/config',params={'link_id':'test-link'}).status_code,200)
        self.assertEqual(customer.get('/api/admin/state').status_code,401)
    def test_editing_access_revokes_old_private_invitation(self):
        l=self.publish('private');customer=TestClient(self.app,base_url=ORIGIN)
        customer.get(l['url'].replace(ORIGIN,''))
        self.assertEqual(self.apply(self.review('link',self.link_data('private')|{'title':'Updated'})).status_code,200)
        self.assertEqual(customer.get('/api/config',params={'link_id':'test-link'}).status_code,401)
    def test_open_payment_blocks_link_and_brand_changes(self):
        self.publish();customer=TestClient(self.app,base_url=ORIGIN);customer.get('/c/test-link')
        row=customer.get('/api/status',params={'link_id':'test-link'}).json();self.app.state.store.claim('new','awaiting_card',row['attemptId'])
        self.assertEqual(self.apply(self.review('link',self.link_data()|{'title':'Changed'})).status_code,409)
        self.assertEqual(self.apply(self.review('brand',{'id':'test-brand','name':'Changed','campaign_id':422})).status_code,409)
    def test_separate_price_offer_does_not_edit_source_price_and_write_runs_once(self):
        self.seed();r=self.review('offer',{'brand_id':'test-brand','sku':SKU,'name':'Brand price','price':'3.00','billing_models':[2]})
        self.assertEqual(self.fake.count('/products'),0)
        a=self.apply(r);self.assertEqual(a.status_code,200,a.text)
        self.assertEqual(self.fake.price,'2.00');self.assertEqual(next(iter(self.fake.products.values()))['price'],3.0)
        self.assertEqual(self.apply(r).json(),a.json());self.assertEqual(self.fake.count('/products'),1)
        self.assertEqual(self.fake.count('/new_order'),0)
    def test_edit_price_updates_only_selected_brand_offer_and_its_link_choices(self):
        self.seed()
        self.apply(self.review('offer',{'brand_id':'test-brand','sku':SKU,'name':'First price','price':'3.00','billing_models':[2]}))
        first=self.client.get('/api/admin/state').json()['offers'][0]
        old_key=f"{first['offer_id']}:{first['product_id']}:2"
        self.apply(self.review('link',self.link_data()|{'options':[old_key]}))
        self.apply(self.review('brand',{'id':'other-brand','name':'Other Brand','campaign_id':422}))
        self.apply(self.review('offer',{'brand_id':'other-brand','sku':SKU,'name':'Other price','price':'5.00','billing_models':[2]}))
        edit={'id':first['id'],'brand_id':'test-brand','sku':SKU,'name':'Updated price','price':'4.00','billing_models':[2]}
        preview=self.review('offer',edit)
        self.assertEqual(preview['preview']['affectedCheckoutLinks'],['test-link'])
        result=self.apply(preview);self.assertEqual(result.status_code,200,result.text)
        records=self.client.get('/api/admin/state').json()
        new=next(o for o in records['offers'] if o['id']==first['id'])
        other=next(o for o in records['offers'] if o['brand_id']=='other-brand')
        self.assertEqual(new['price'],'4.00');self.assertEqual(other['price'],'5.00')
        self.assertEqual(records['links'][0]['options'],[f"{new['offer_id']}:{new['product_id']}:2"])
        self.assertEqual(self.fake.products[first['product_id']]['price'],3.0)
        self.assertEqual(self.fake.price,'2.00')

    def test_price_edit_cannot_replace_choices_during_open_payment(self):
        self.seed();self.apply(self.review('offer',{'brand_id':'test-brand','sku':SKU,'name':'First price','price':'3.00','billing_models':[2]}))
        record=self.client.get('/api/admin/state').json()['offers'][0]
        self.apply(self.review('link',self.link_data()|{'options':[f"{record['offer_id']}:{record['product_id']}:2"]}))
        row=self.app.state.store.create(422,SKU,'test-link')
        self.app.state.store.claim('new','awaiting_card',row)
        r=self.review('offer',{'id':record['id'],'brand_id':'test-brand','sku':SKU,'name':'Updated','price':'4.00','billing_models':[2]})
        before=self.fake.count('/products')
        self.assertEqual(self.apply(r).status_code,409)
        self.assertEqual(self.fake.count('/products'),before)

    def test_uncertain_offer_write_keeps_created_id_and_never_retries(self):
        self.seed();r=self.review('offer',{'brand_id':'test-brand','sku':SKU,'name':'Brand price','price':'3.00','billing_models':[2]})
        self.fake.fail_offer=True
        self.assertEqual(self.apply(r).status_code,502);self.assertEqual(self.apply(r).status_code,409)
        review=self.client.get('/api/admin/state').json()['reviews'][0]
        self.assertEqual(review['status'],'reconcile');self.assertIn('product',review['result']['created'])
        self.assertEqual(self.fake.count('/products'),1)
    def test_managed_attempt_cannot_be_reused_on_other_link(self):
        self.publish()
        self.assertEqual(self.apply(self.review('link',self.link_data(id='other-link'))).status_code,200)
        customer=TestClient(self.app,base_url=ORIGIN);customer.get('/c/test-link')
        s=customer.get('/api/status',params={'link_id':'test-link'}).json()
        customer.get('/c/other-link')
        self.assertEqual(customer.get('/api/status',params={'link_id':'other-link'},headers={'X-Checkout-Attempt':s['attemptId']}).status_code,409)
    def test_invalid_configuration_is_clean_validation_error(self):
        r=self.post('reviews',{'kind':'brand','data':{'id':'bad','name':'Brand','logo_url':'javascript:bad'}})
        self.assertEqual(r.status_code,422);self.assertNotIn('javascript:',r.text)
    def test_new_public_purchase_keeps_link_scope(self):
        self.publish();customer=TestClient(self.app,base_url=ORIGIN);customer.get('/c/test-link')
        c=customer.get('/api/config',params={'link_id':'test-link'}).json();s=customer.get('/api/status',params={'link_id':'test-link'}).json()
        self.app.state.store.claim('new','captured',s['attemptId'],order_id='900001')
        h={'Origin':ORIGIN,'X-CSRF-Token':c['csrfToken'],'X-Checkout-Attempt':s['attemptId']}
        r=customer.post('/api/new-purchase',params={'link_id':'test-link'},headers=h,json={'previous_attempt_id':s['attemptId']})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.app.state.store.read(r.json()['attemptId'])['link_id'],'test-link')

    def test_link_can_select_campaign_without_preexisting_brand_mapping(self):
        self.apply(self.review('sku',{'sku':SKU,'name':'Test SKU','product_id':54537}))
        data=self.link_data();data.pop('brand_id');data['campaign_id']=422
        r=self.review('link',data);self.assertEqual(self.client.get('/api/admin/state').json()['brands'],[])
        self.assertEqual(r['preview']['stickyWrites'],[]);self.assertEqual(r['preview']['after']['campaign_id'],422)
        a=self.apply(r);self.assertEqual(a.status_code,200,a.text);self.assertEqual(self.apply(r).json(),a.json())
        state=self.client.get('/api/admin/state').json();self.assertEqual(len(state['brands']),1)
        self.assertEqual(state['links'][0]['brand_id'],state['brands'][0]['id'])
        self.assertNotIn('_link_brand',state['links'][0]);self.assertEqual(self.client.get('/c/test-link').status_code,200)
        self.assertFalse(self.fake.calls)
    def test_direct_link_reuses_campaign_mapping_and_rejects_conflicting_brand(self):
        self.seed();data=self.link_data();data.pop('brand_id');data['campaign_id']=422
        self.assertEqual(self.apply(self.review('link',data)).status_code,200)
        state=self.client.get('/api/admin/state').json();self.assertEqual(len(state['brands']),1);self.assertEqual(state['links'][0]['brand_id'],'test-brand')
        self.assertEqual(self.post('reviews',{'kind':'link','data':self.link_data()|{'campaign_id':167}}).status_code,422)
    def test_direct_link_cannot_overwrite_other_campaign_identifier(self):
        self.apply(self.review('brand',{'id':'campaign-422','name':'Other brand','campaign_id':167}))
        self.apply(self.review('sku',{'sku':SKU,'name':'Test SKU','product_id':54537}))
        data=self.link_data();data.pop('brand_id');data['campaign_id']=422
        self.assertEqual(self.post('reviews',{'kind':'link','data':data}).status_code,409)
        self.assertEqual(self.client.get('/api/admin/state').json()['brands'][0]['campaign_id'],167)

if __name__=='__main__':unittest.main()
