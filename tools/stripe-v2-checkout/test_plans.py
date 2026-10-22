"""Multi-treatment plan selection: fixture-only catalog, access and payment boundaries."""
import copy
import unittest
from fastapi.testclient import TestClient
import test_master as master_helpers
from test_checkout import ORIGIN,CONTACT
from plans import choice_id

class PlanTests(unittest.TestCase):
    setUp=master_helpers.MasterTests.setUp
    tearDown=master_helpers.MasterTests.tearDown
    post=master_helpers.MasterTests.post
    review=master_helpers.MasterTests.review
    apply=master_helpers.MasterTests.apply
    state=master_helpers.MasterTests.state
    preset=master_helpers.MasterTests.preset
    provision=master_helpers.MasterTests.provision
    def save(self,kind,data):
        r=self.review(kind,data);result=self.apply(r);self.assertEqual(result.status_code,200,result.text);return r
    def seed(self):
        self.therapy={'id':'weight-loss','name':'Weight Loss','enabled':True,'treatments':[{'id':'tirzepatide','name':'Tirzepatide'},{'id':'semaglutide','name':'Semaglutide'}]}
        self.save('therapy',self.therapy)
        self.save('brand',{'id':'test-brand','name':'QA brand','campaign_id':422,'color':'#6260c3'})
        for sku,treatment in [('TIRZ-1M','tirzepatide'),('SEMA-3M','semaglutide')]:
            p=self.preset();p.update(sku=sku,name=sku,product_id=None,therapy_id='weight-loss',treatment_id=treatment,product_duration_months=1 if treatment=='tirzepatide' else 3)
            p['offers']=[{'id':'standard','name':'Standard','price':'449.00','billing_models':[2,3]}]
            self.save('master',p)
        self.provision()
        options=self.client.get('/api/admin/plan-options',params={'brand_id':'test-brand','campaign_id':422,'therapy_id':'weight-loss'})
        self.assertEqual(options.status_code,200,options.text)
        self.plan={'id':'weight-loss-plans','title':'Choose your plan','brand_id':'test-brand','campaign_id':422,'therapy_id':'weight-loss','visibility':'public','enabled':True,
            'entries':[{'sku':e['sku'],'options':[o['key'] for o in e['options']]} for e in options.json()['entries']]}
        return self.plan
    def customer(self):return TestClient(self.app,base_url=ORIGIN)
    def test_local_review_has_no_payment_or_sticky_writes_and_hides_children(self):
        self.seed();before=copy.deepcopy(self.fake.calls);r=self.save('plan_checkout',self.plan)
        self.assertEqual(r['preview']['stickyWrites'],[]);self.assertEqual(self.fake.calls,before)
        state=self.state();self.assertEqual(len(state['links']),2);self.assertEqual(len(state['planCheckouts']),1)
        c=self.customer();response=c.get('/api/plans/weight-loss-plans');self.assertEqual(response.status_code,200)
        data=response.json();self.assertEqual({t['name'] for t in data['treatments']},{'Tirzepatide','Semaglutide'})
        self.assertEqual({e['durationMonths'] for e in data['entries']},{1,3});self.assertEqual(data['branding']['color'],'#6260c3')
        for entry in data['entries']:self.assertEqual({o['recurring'] for o in entry['options']},{False,True})
        self.assertNotIn('NEVER_EXPOSE',response.text);self.assertNotIn('private123',response.text)
        self.assertEqual(c.get('/plans/weight-loss-plans').status_code,200)
    def test_private_invitation_and_child_access_only_for_selected_member(self):
        self.seed();self.plan['visibility']='private';self.save('plan_checkout',self.plan);c=self.customer();path='/plans/'+self.plan['id']
        self.assertEqual(c.get(path).status_code,401);self.assertEqual(c.get('/api'+path).status_code,401)
        entry=self.plan['entries'][0];params={'sku':entry['sku'],'option':entry['options'][0]}
        self.assertEqual(c.get(path+'/choose',params=params).status_code,401)
        self.assertEqual(c.get(path+'?access=invalid').status_code,401)
        self.assertEqual(c.get(self.state()['planCheckouts'][0]['url']).status_code,200)
        child=choice_id(self.plan['id'],entry['sku']);self.assertEqual(c.get('/c/'+child).status_code,401)
        r=c.get(path+'/choose',params=params,follow_redirects=False);self.assertEqual(r.status_code,303);self.assertIn('selection=',r.headers['location'])
        self.assertEqual(c.get(r.headers['location']).status_code,200)
        other=choice_id(self.plan['id'],self.plan['entries'][1]['sku']);self.assertEqual(c.get('/c/'+other).status_code,401)
        self.assertEqual(c.get(path+'/choose',params=params|{'option':'706:54537:2'}).status_code,422)
        self.assertEqual(c.get(path+'/choose',params=params|{'sku':'NOT-ENABLED'}).status_code,404)
        self.assertEqual(self.fake.count('/new_order'),0)
    def test_selected_sku_and_option_reach_quote_and_capture_exactly_once(self):
        self.seed();self.save('plan_checkout',self.plan);c=self.customer();entry=next(e for e in self.plan['entries'] if e['sku']=='SEMA-3M');selection=next(k for k in entry['options'] if k.endswith(':2'))
        c.get('/plans/weight-loss-plans/choose',params={'sku':entry['sku'],'option':selection})
        params={'link_id':choice_id(self.plan['id'],entry['sku'])};cfg=c.get('/api/config',params=params).json()
        headers={'Origin':ORIGIN,'X-CSRF-Token':cfg['csrfToken'],'X-Checkout-Attempt':cfg['attemptId']}
        def post(path,data):return c.post('/api/'+path,params=params,headers=headers,json=data)
        q=post('quote',{'contact':CONTACT,'selection':selection,'shipping_id':2});self.assertEqual(q.status_code,200,q.text)
        a=post('authorize',{'quote_id':q.json()['id'],'recurring_consent':False});self.assertEqual(a.status_code,200,a.text)
        self.fake.order_total='449.00';r=post('capture',{});self.assertEqual(r.status_code,200,r.text);self.assertEqual(post('capture',{}).status_code,200)
        order=next(b for _,p,b in self.fake.calls if p.endswith('/new_order'));o=order['offers'][0]
        self.assertEqual([o['offer_id'],o['product_id'],o['billing_model_id']],[int(k) for k in selection.split(':')]);self.assertEqual(self.fake.count('/new_order'),1)
    def test_invalid_brand_therapy_and_purchase_options_are_rejected(self):
        self.seed()
        for fields in ({'brand_id':'missing'},{'campaign_id':167},{'therapy_id':'missing'},{'entries':[{'sku':'TIRZ-1M','options':['706:54537:2']}]}):
            self.assertEqual(self.post('reviews',{'kind':'plan_checkout','data':self.plan|fields}).status_code,422)
        self.save('plan_checkout',self.plan);child=self.app.state.admin.get('link',choice_id(self.plan['id'],'TIRZ-1M'));child={k:v for k,v in child.items() if k not in ('revision','plan_checkout_id')}
        self.assertEqual(self.post('reviews',{'kind':'link','data':child}).status_code,422)
    def test_revisions_revoke_invitations_and_removed_members(self):
        self.seed();self.plan['visibility']='private';self.save('plan_checkout',self.plan);c=self.customer();oldurl=self.state()['planCheckouts'][0]['url'];c.get(oldurl)
        entry=self.plan['entries'][0];c.get('/plans/weight-loss-plans/choose',params={'sku':entry['sku'],'option':entry['options'][0]})
        self.plan['entries']=self.plan['entries'][1:];self.save('plan_checkout',self.plan)
        self.assertEqual(c.get(oldurl).status_code,401);self.assertEqual(c.get('/api/plans/weight-loss-plans').status_code,401)
        self.assertEqual(c.get('/c/'+choice_id(self.plan['id'],entry['sku'])).status_code,404)
    def test_disabled_parent_and_therapy_disable_child_checkout(self):
        self.seed();self.save('plan_checkout',self.plan);c=self.customer();entry=self.plan['entries'][0];c.get('/plans/weight-loss-plans/choose',params={'sku':entry['sku'],'option':entry['options'][0]})
        self.save('plan_checkout',self.plan|{'enabled':False});self.assertEqual(c.get('/api/plans/weight-loss-plans').status_code,404);self.assertEqual(c.get('/c/'+choice_id(self.plan['id'],entry['sku'])).status_code,404)
        self.save('plan_checkout',self.plan);self.save('therapy',self.therapy|{'enabled':False});self.assertEqual(c.get('/api/plans/weight-loss-plans').status_code,409)
    def test_open_payment_blocks_plan_therapy_and_master_metadata_edits(self):
        self.seed();self.save('plan_checkout',self.plan);key=self.app.state.store.create(422,'TIRZ-1M',link_id=choice_id(self.plan['id'],'TIRZ-1M'));self.app.state.store.claim('new','awaiting_card',key)
        for kind,data in [('plan_checkout',self.plan|{'title':'New title'}),('therapy',self.therapy|{'name':'New name'})]:self.assertEqual(self.apply(self.review(kind,data)).status_code,409)
        m=self.preset();m.update(therapy_id='weight-loss',treatment_id='tirzepatide',product_duration_months=6)
        self.assertEqual(self.apply(self.review('master',m)).status_code,409)
    def test_metadata_only_change_preserves_revision_and_cannot_remove_used_treatment(self):
        self.seed();before=next(m for m in self.state()['masters'] if m['sku']=='TIRZ-1M');p={k:v for k,v in before.items() if k in self.preset() or k in ('therapy_id','treatment_id')};p['product_duration_months']=6
        self.save('master',p);after=next(m for m in self.state()['masters'] if m['sku']=='TIRZ-1M');self.assertEqual(after['revision'],before['revision'])
        self.assertEqual(self.post('reviews',{'kind':'therapy','data':self.therapy|{'treatments':[self.therapy['treatments'][0]]}}).status_code,422)
    def test_remote_price_drift_and_local_config_drift_require_new_review(self):
        self.seed();r=self.review('plan_checkout',self.plan);pid=self.state()['offers'][0]['product_id'];self.fake.products[pid]['price']=999
        self.assertEqual(self.apply(r).status_code,409)
        r=self.review('plan_checkout',self.plan);self.save('therapy',self.therapy|{'name':'Changed therapy'});self.assertEqual(self.apply(r).status_code,409)
    def test_brand_price_replacement_updates_plan_selection(self):
        self.seed();self.save('plan_checkout',self.plan);o=self.state()['offers'][0];edit={k:o[k] for k in ('id','brand_id','sku','name','billing_models','configuration')};edit['price']='123.00';self.save('offer',edit)
        data=self.customer().get('/api/plans/weight-loss-plans').json();entry=next(e for e in data['entries'] if e['sku']==o['sku']);self.assertTrue(entry['available']);self.assertEqual({o['basePrice'] for o in entry['options']},{'123.0'})
        self.assertEqual(set(next(e for e in self.state()['planCheckouts'][0]['entries'] if e['sku']==o['sku'])['options']),{o['key'] for o in entry['options']})
    def test_owner_and_csrf_required_and_unavailable_option_fails_closed(self):
        self.seed();self.save('plan_checkout',self.plan);c=self.customer();self.assertEqual(c.get('/api/admin/plan-options',params={'brand_id':'test-brand','campaign_id':422,'therapy_id':'weight-loss'}).status_code,401)
        self.assertEqual(self.client.post('/api/admin/reviews',json={'kind':'therapy','data':self.therapy}).status_code,403)
        
        for product in self.fake.products.values():product['archived_flag']=1
        r=c.get('/api/plans/weight-loss-plans');self.assertEqual(r.status_code,200);self.assertTrue(all(not e['available'] for e in r.json()['entries']))


    def test_shared_public_api_child_needs_no_prior_invitation_and_keeps_old_attempts(self):
        self.seed();self.plan['visibility']='private';self.save('plan_checkout',self.plan)
        admin=self.app.state.admin;entry=self.plan['entries'][0]
        old_id=choice_id(self.plan['id'],entry['sku'])
        original=copy.deepcopy(admin.get('link',old_id))
        held=self.app.state.store.create(422,entry['sku'],link_id=old_id)
        self.app.state.store.claim('new','awaiting_card',held)
        new_plan=copy.deepcopy(admin.get('plan_checkout',self.plan['id']))
        new_plan.update(id='public-api-copy',visibility='public',revision=1)
        new_id=choice_id(new_plan['id'],entry['sku'])
        public_child=original|{'id':new_id,'plan_checkout_id':new_plan['id'],'visibility':'public','revision':1}
        admin.put('plan_checkout',new_plan['id'],new_plan)
        admin.put('link',new_id,public_child)
        for _ in range(2):
            with self.customer() as customer:
                self.assertEqual(customer.get('/c/'+old_id).status_code,401)
                self.assertEqual(customer.get('/c/'+new_id,params={'selection':entry['options'][0]}).status_code,200)
                self.assertFalse(any(c.name.startswith('link_access_') for c in customer.cookies.jar))
                response=customer.get('/api/config',params={'link_id':new_id})
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(response.json()['sku'],entry['sku'])
        self.assertEqual(admin.get('link',old_id),original)
        self.assertEqual(self.app.state.store.read(held)['status'],'awaiting_card')
        admin.put('plan_checkout',new_plan['id'],new_plan|{'enabled':False})
        self.assertEqual(self.customer().get('/c/'+new_id).status_code,404)
        self.assertEqual(self.fake.count('/authorize_payment'),0)

if __name__=='__main__':unittest.main()
