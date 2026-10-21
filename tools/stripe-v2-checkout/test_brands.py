"""Brand design and campaign isolation regressions; no external calls."""
import copy
import unittest
from fastapi.testclient import TestClient
import test_master as helpers
from test_checkout import ORIGIN
from catalog import resolve

class BrandTests(unittest.TestCase):
    setUp=helpers.MasterTests.setUp
    tearDown=helpers.MasterTests.tearDown
    post=helpers.MasterTests.post
    review=helpers.MasterTests.review
    apply=helpers.MasterTests.apply
    state=helpers.MasterTests.state
    preset=helpers.MasterTests.preset
    seed=helpers.MasterTests.seed

    def setup_campaign(self,cid=None,name=None):
        data={'brand_id':'test-brand'}
        data.update({'campaign_id':cid} if cid else {'name':name,'template_id':422})
        r=self.apply(self.review('campaign_setup',data))
        self.assertEqual(r.status_code,200,r.text)
        self.assertTrue(r.json()['validation']['ready'])
        return r.json()

    def test_two_campaigns_keep_existing_link_and_quote_fingerprint(self):
        self.seed();self.setup_campaign(422)
        first=copy.deepcopy(self.state()['links'][0]);a=self.app.state.admin
        link,brand=a.link(first['id']);before=a.filter_catalog(resolve(self.fake,422,'TIRZ-1M'),link,brand)
        self.setup_campaign(167)
        brand=self.state()['brands'][0]
        self.assertEqual(brand['campaign_id'],422);self.assertEqual(set(brand['campaign_ids']),{422,167})
        self.assertEqual(next(l for l in self.state()['links'] if l['campaign_id']==422),first)
        link,brand=a.link(first['id']);after=a.filter_catalog(resolve(self.fake,422,'TIRZ-1M'),link,brand)
        self.assertEqual(before['fingerprint'],after['fingerprint'])
        links=self.state()['links'];self.assertEqual({l['campaign_id'] for l in links},{422,167})
        for l in links:
            self.assertEqual(a.link(l['id'])[1]['campaign_id'],l['campaign_id'])
            self.assertTrue(self.post('master-validation',{'brand_id':'test-brand','campaign_id':l['campaign_id']}).json()['ready'])
        count=len(self.fake.products);self.setup_campaign(167);self.assertEqual(len(self.fake.products),count)

    def test_two_new_campaigns_append_to_same_brand(self):
        self.seed();one=self.setup_campaign(name='First campaign')['created']['campaign'];two=self.setup_campaign(name='Second campaign')['created']['campaign']
        b=self.state()['brands'][0];self.assertEqual(b['campaign_id'],422)
        self.assertEqual(set(b['campaign_ids']),{422,one,two})
        self.assertEqual({l['campaign_id'] for l in self.state()['links']},{one,two})
        self.assertEqual({o['campaign_id'] for o in self.state()['offers']},{one,two})
        count=len(self.fake.products);self.setup_campaign(one);self.assertEqual(len(self.fake.products),count)

    def test_price_edit_in_second_campaign_does_not_change_first_campaign(self):
        self.seed();self.setup_campaign(422);self.setup_campaign(167)
        before=copy.deepcopy(self.state());old=next(o for o in before['offers'] if o['campaign_id']==167)
        data={k:old[k] for k in ('id','brand_id','campaign_id','sku','name','billing_models','configuration')};data['price']='123.00'
        self.assertEqual(self.apply(self.review('offer',data)).status_code,200)
        first=lambda rows:next(r for r in rows if r['campaign_id']==422)
        self.assertEqual(first(self.state()['offers']),first(before['offers']))
        self.assertEqual(first(self.state()['links']),first(before['links']))
        changed=next(o for o in self.state()['offers'] if o['campaign_id']==167)
        self.assertEqual(changed['price'],'123.00')
        self.assertEqual(self.post('reviews',{'kind':'offer','data':data|{'campaign_id':422}}).status_code,422)

    def test_legacy_link_without_campaign_remains_on_primary_after_brand_edit(self):
        self.seed();self.setup_campaign(422);a=self.app.state.admin
        l=a.records('link')[0];l.pop('campaign_id');a.put('link',l['id'],l)
        b=a.get('brand','test-brand');b.pop('campaign_ids',None);a.put('brand',b['id'],b)
        self.setup_campaign(167)
        self.assertEqual(a.link(l['id'])[1]['campaign_id'],422)
        self.assertEqual(self.apply(self.review('brand',b|{'campaign_id':167,'color':'#6f3380'})).status_code,200)
        self.assertEqual(a.link(l['id'])[1]['campaign_id'],422)
        self.assertEqual(set(a.get('brand',b['id'])['campaign_ids']),{422,167})

    def test_theme_propagates_without_reissuing_links_or_writing_sticky(self):
        self.seed();self.setup_campaign(422);self.setup_campaign(167)
        a=self.app.state.admin;links=copy.deepcopy(self.state()['links']);calls=len(self.fake.calls)
        theme={'color':'#5b287c','background_color':'#faf0ff','text_color':'#201a29','button_text_color':'#fefefe','font':'serif','layout':'stacked','support_email':'care@example.com'}
        self.assertEqual(self.apply(self.review('brand',{'id':'other-brand','name':'Other brand'})).status_code,200)
        other=copy.deepcopy(a.get('brand','other-brand'))
        b=a.get('brand','test-brand');review=self.review('brand',b|theme)
        self.assertEqual(len(review['preview']['affectedCheckoutLinks']),2)
        self.assertEqual(self.apply(review).status_code,200);self.assertEqual(self.state()['links'],links)
        for l in links:
            with TestClient(self.app,base_url=ORIGIN) as client:
                self.assertEqual(client.get(l['url']).status_code,200)
                config=client.get('/api/config',params={'link_id':l['id']}).json()
                for k,v in theme.items():self.assertEqual(config['branding'][k],v)
        self.assertEqual(a.get('brand','other-brand'),other);self.assertEqual(len(self.fake.calls),calls)

    def test_unattached_campaign_cannot_receive_brand_link(self):
        self.seed();self.setup_campaign(422)
        l=self.state()['links'][0]
        data={k:l[k] for k in ('id','brand_id','sku','title','visibility','options','enabled')};data.update(id='wrong-campaign',campaign_id=167)
        self.assertEqual(self.post('reviews',{'kind':'link','data':data}).status_code,422)
        self.assertEqual(self.post('reviews',{'kind':'provision','data':{'brand_id':'test-brand','campaign_id':167}}).status_code,422)

    def test_pending_target_campaign_payment_blocks_assignment_even_with_other_primary(self):
        self.seed();r=self.review('campaign_setup',{'brand_id':'test-brand','campaign_id':167})
        key=self.app.state.store.create(167,'TIRZ-1M');self.app.state.store.claim('new','awaiting_card',key)
        self.assertEqual(self.apply(r).status_code,409);self.assertFalse(self.fake.calls)

    def test_invalid_theme_values_are_rejected_before_apply(self):
        for field,value in [('font','external-font'),('layout','custom'),('color','url(https://x)'),('background_color','#123'),('text_color','red'),('button_text_color','transparent'),('logo_url','javascript:alert(1)'),('campaign_ids',[0])]:
            with self.subTest(field=field):
                r=self.post('reviews',{'kind':'brand','data':{'id':'new-brand','name':'New brand',field:value}})
                self.assertEqual(r.status_code,422,r.text)
        self.assertEqual(self.state()['brands'],[])

    def test_category_is_local_and_regroups_existing_master_without_billing_revision(self):
        self.seed();self.setup_campaign(422)
        before=copy.deepcopy(self.state());calls=len(self.fake.calls)
        data=self.preset()|{'category':'  Weight Loss  '}
        r=self.review('master',data);self.assertEqual(r['preview']['stickyWrites'],[])
        self.assertEqual(self.apply(r).status_code,200)
        after=self.state();self.assertEqual(after['masters'][0]['category'],'Weight Loss')
        self.assertEqual(after['masters'][0]['revision'],before['masters'][0]['revision'])
        self.assertEqual(after['links'],before['links']);self.assertEqual(after['offers'],before['offers'])
        self.assertEqual(len(self.fake.calls),calls)
        self.assertTrue(self.post('master-validation',{'brand_id':'test-brand'}).json()['skus'][0]['masterCurrent'])
        self.assertEqual(self.apply(self.review('master',self.preset())).status_code,200)
        self.assertEqual(self.state()['masters'][0]['category'],'Weight Loss')
        bad=self.post('reviews',{'kind':'master','data':self.preset()|{'category':'x'*81}})
        self.assertEqual(bad.status_code,422)

    def test_second_brand_on_same_campaign_does_not_change_legacy_link_design(self):
        self.seed();self.setup_campaign(422);a=self.app.state.admin
        link=a.records('link')[0];link.pop('campaign_id');a.put('link',link['id'],link)
        self.assertEqual(self.apply(self.review('brand',{'id':'purple-brand','name':'Purple Brand','campaign_id':422,'color':'#6260c3'})).status_code,200)
        legacy,owner=a.link(link['id']);self.assertEqual(owner['id'],'test-brand')
        c=a.filter_catalog(resolve(self.fake,422,'TIRZ-1M'),legacy,owner)
        self.assertEqual(c['branding']['color'],'#245844')
        self.assertEqual(self.apply(self.review('brand',a.get('brand','test-brand')|{'color':'#194f64'})).status_code,200)
        legacy,owner=a.link(link['id']);self.assertEqual(owner['color'],'#194f64')
        self.assertEqual(a.get('brand','purple-brand')['color'],'#6260c3')

    def test_product_duration_changes_do_not_change_prices_or_billing_for_legacy_records(self):
        self.seed();self.setup_campaign(422);a=self.app.state.admin
        old=a.get('master','TIRZ-1M');old.pop('product_duration_months',None);old.pop('fulfillment_product_id',None);a.put('master','TIRZ-1M',old)
        before=copy.deepcopy(self.state());calls=len(self.fake.calls)
        r=self.review('master',self.preset()|{'product_duration_months':3})
        self.assertEqual(r['preview']['stickyWrites'],[]);self.assertEqual(self.apply(r).status_code,200)
        after=self.state();self.assertEqual(after['masters'][0]['product_duration_months'],3)
        self.assertEqual(after['masters'][0]['revision'],before['masters'][0]['revision'])
        self.assertEqual(after['offers'],before['offers']);self.assertEqual(after['links'],before['links'])
        self.assertEqual(after['masters'][0]['billing_terms'],before['masters'][0]['billing_terms']);self.assertEqual(len(self.fake.calls),calls)
        legacy=self.preset();legacy.pop('product_duration_months')
        self.assertEqual(self.apply(self.review('master',legacy)).status_code,200)
        self.assertEqual(self.state()['masters'][0]['product_duration_months'],3)

    def test_product_duration_bounds_and_billing_mapping_are_explicit(self):
        for value in (0,37,1.5,'1',True):
            self.assertEqual(self.post('reviews',{'kind':'master','data':self.preset()|{'product_duration_months':value}}).status_code,422)
        p=self.preset();p['offers']=[{'id':'once','name':'One-time purchase','price':'499.00','billing_models':[2]}, {'id':'repeat','name':'Subscription','price':'399.00','billing_models':[3,4]}]
        self.assertEqual(self.apply(self.review('master',p)).status_code,200)
        self.assertEqual(self.state()['masters'][0]['product_duration_months'],1)
        self.assertEqual([o['billing_models'] for o in self.state()['masters'][0]['offers']],[[2],[3,4]])
        self.assertEqual([o['price'] for o in self.state()['masters'][0]['offers']],['499.00','399.00'])
        self.assertFalse(self.fake.calls)

if __name__=='__main__':unittest.main()
