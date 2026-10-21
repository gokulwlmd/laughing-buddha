"""Duration purchase options preserve SKU, campaign and payment boundaries."""
import copy
import unittest
import test_plans as helpers
from plans import choice_id
from test_checkout import ORIGIN,CONTACT

class PurchaseOptionTests(unittest.TestCase):
    setUp=helpers.PlanTests.setUp
    tearDown=helpers.PlanTests.tearDown
    post=helpers.PlanTests.post
    review=helpers.PlanTests.review
    apply=helpers.PlanTests.apply
    state=helpers.PlanTests.state
    preset=helpers.PlanTests.preset
    provision=helpers.PlanTests.provision
    save=helpers.PlanTests.save
    customer=helpers.PlanTests.customer
    def seed(self):
        helpers.PlanTests.seed(self)
        p=self.preset();p.update(sku='SEMA-1M',name='Semaglutide one month',product_id=None,therapy_id='weight-loss',treatment_id='semaglutide',product_duration_months=1)
        p['offers']=[{'id':'standard','name':'Standard','price':'299.00','billing_models':[2,3]}];self.save('master',p);self.provision()
        self.monthly={'id':'monthly','therapy_id':'weight-loss','name':'1-month plan','duration_months':1,'skus':['TIRZ-1M','SEMA-1M'],'payment_types':['once','subscription'],'enabled':True}
        self.quarterly=self.monthly|{'id':'quarterly','name':'3-month plan','duration_months':3,'skus':['SEMA-3M']}
        self.save('purchase_option',self.monthly);self.save('purchase_option',self.quarterly)
        self.checkout={k:v for k,v in self.plan.items() if k!='entries'}|{'purchase_option_ids':['monthly','quarterly']}
    def publish(self):self.save('plan_checkout',self.checkout)
    def test_options_save_locally_and_checkout_derives_prices_and_choices(self):
        self.seed();before=copy.deepcopy(self.fake.calls);self.publish();self.assertEqual(self.fake.calls,before)
        data=self.customer().get('/api/plans/'+self.checkout['id']).json()
        self.assertEqual([p['durationMonths'] for p in data['purchaseOptions']],[1,3]);monthly=[e for e in data['entries'] if e['purchaseOptionId']=='monthly'];self.assertEqual({e['sku'] for e in monthly},{'TIRZ-1M','SEMA-1M'})
        self.assertEqual({o['basePrice'] for e in monthly for o in e['options']},{'299.0','449.0'})
        for entry in monthly:self.assertEqual({o['recurring'] for o in entry['options']},{True,False})
        self.assertEqual(len(self.state()['links']),3)
    def test_mismatched_duration_and_therapy_rejected_and_later_master_edits_guarded(self):
        self.seed()
        for data in (self.monthly|{'skus':['SEMA-3M']},self.monthly|{'duration_months':3},self.monthly|{'therapy_id':'missing'}):
            self.assertEqual(self.post('reviews',{'kind':'purchase_option','data':data}).status_code,422)
        p=self.preset();p.update(therapy_id='weight-loss',treatment_id='tirzepatide',product_duration_months=3)
        r=self.post('reviews',{'kind':'master','data':p});self.assertEqual(r.status_code,422);self.assertIn('Remove this SKU',r.text)
    def test_empty_option_is_a_saveable_draft_but_cannot_be_published(self):
        self.seed();self.save('purchase_option',self.monthly|{'skus':[]})
        r=self.post('reviews',{'kind':'plan_checkout','data':self.checkout});self.assertEqual(r.status_code,422);self.assertIn('assign matching-duration',r.text)
    def test_user_cannot_inject_skus_choices_or_unrelated_purchase_options(self):
        self.seed()
        for fields in ({'purchase_option_ids':['missing']},{'purchase_option_ids':['monthly','monthly']},{'entries':self.plan['entries']}):self.assertEqual(self.post('reviews',{'kind':'plan_checkout','data':self.checkout|fields}).status_code,422)
        self.save('purchase_option',self.monthly|{'enabled':False});self.assertEqual(self.post('reviews',{'kind':'plan_checkout','data':self.checkout}).status_code,422)
    def test_shared_sku_across_same_duration_options_keeps_payment_access_separate(self):
        self.seed();once=self.monthly|{'payment_types':['once'],'skus':['TIRZ-1M']};sub=once|{'id':'monthly-sub','payment_types':['subscription']};self.save('purchase_option',once);self.save('purchase_option',sub)
        self.checkout['purchase_option_ids']=['monthly','monthly-sub'];self.publish();c=self.customer();data=c.get('/api/plans/'+self.checkout['id']).json();one=next(e for e in data['entries'] if e['purchaseOptionId']=='monthly');rec=next(e for e in data['entries'] if e['purchaseOptionId']=='monthly-sub')
        path='/plans/'+self.checkout['id']+'/choose';params={'sku':'TIRZ-1M','purchase_option_id':'monthly','option':rec['options'][0]['key']}
        self.assertEqual(c.get(path,params=params).status_code,422);self.assertEqual(c.get(path,params=params|{'purchase_option_id':''}).status_code,404)
        self.assertEqual(c.get(path,params=params|{'option':one['options'][0]['key']}).status_code,200)
        child=choice_id(self.checkout['id'],'TIRZ-1M','monthly');cfg=c.get('/api/config',params={'link_id':child}).json();self.assertEqual(len(cfg['options']),1);self.assertFalse(cfg['options'][0]['recurring'])
        self.assertEqual(c.get('/c/'+choice_id(self.checkout['id'],'TIRZ-1M','monthly-sub')).status_code,401)
    def test_changes_require_republication_but_disable_is_immediate(self):
        self.seed();self.publish();before=self.state()['planCheckouts'][0];self.save('purchase_option',self.monthly|{'skus':['TIRZ-1M'],'payment_types':['once']});state=self.state()['planCheckouts'][0]
        self.assertFalse(state['purchaseOptionsCurrent']);self.assertEqual(state['entries'],before['entries']);self.publish();after=self.state()['planCheckouts'][0];self.assertTrue(after['purchaseOptionsCurrent']);monthly=[e for e in after['entries'] if e['purchase_option_id']=='monthly'];self.assertEqual(len(monthly),1);self.assertEqual(len(monthly[0]['options']),1)
        c=self.customer();params={'sku':'TIRZ-1M','purchase_option_id':'monthly','option':monthly[0]['options'][0]};c.get('/plans/'+self.checkout['id']+'/choose',params=params)
        self.save('purchase_option',self.monthly|{'enabled':False});self.assertEqual(c.get('/c/'+choice_id(self.checkout['id'],'TIRZ-1M','monthly')).status_code,404)
        data=c.get('/api/plans/'+self.checkout['id']).json();self.assertTrue(all(not e['available'] for e in data['entries'] if e['purchaseOptionId']=='monthly'))
    def test_open_payment_blocks_purchase_option_mutation(self):
        self.seed();self.publish();child=choice_id(self.checkout['id'],'TIRZ-1M','monthly');key=self.app.state.store.create(422,'TIRZ-1M',link_id=child);self.app.state.store.claim('new','awaiting_card',key)
        self.assertEqual(self.apply(self.review('purchase_option',self.monthly|{'enabled':False})).status_code,409)
    def test_unmanaged_same_sku_offer_is_not_silently_added(self):
        self.seed();self.fake.products[54537]=self.fake.detail('/api/v2/products/2856')|{'id':54537,'price':'1.00'};self.publish()
        entries=self.state()['planCheckouts'][0]['entries'];self.assertTrue(all(not key.startswith('706:') for e in entries for key in e['options']))
    def test_brand_price_replacement_follows_child_and_new_preview(self):
        self.seed();self.publish();offer=next(o for o in self.state()['offers'] if o['sku']=='TIRZ-1M');edit={k:offer[k] for k in ('id','brand_id','sku','name','billing_models','configuration')};edit['price']='222.00';self.save('offer',edit)
        data=self.customer().get('/api/plans/'+self.checkout['id']).json();entry=next(e for e in data['entries'] if e['sku']=='TIRZ-1M');self.assertEqual({o['basePrice'] for o in entry['options']},{'222.0'});self.publish()
        entry=next(e for e in self.customer().get('/api/plans/'+self.checkout['id']).json()['entries'] if e['sku']=='TIRZ-1M');self.assertEqual({o['basePrice'] for o in entry['options']},{'222.0'})
    def test_admin_choices_report_missing_assignment_and_do_not_charge(self):
        self.seed();self.save('brand',{'id':'second-brand','name':'Other','campaign_id':167})
        data=self.client.get('/api/admin/plan-options',params={'brand_id':'second-brand','campaign_id':167,'therapy_id':'weight-loss'}).json();self.assertTrue(all(not p['ready'] for p in data['purchaseOptions']));self.assertEqual(self.fake.count('/authorize_payment'),0)
    def test_preview_is_stale_after_purchase_option_change(self):
        self.seed();r=self.review('plan_checkout',self.checkout);self.save('purchase_option',self.monthly|{'name':'Updated monthly plan'});self.assertEqual(self.apply(r).status_code,409)

if __name__=='__main__':unittest.main()
