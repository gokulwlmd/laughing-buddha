"""Site setup uses fake Sticky only; assertions cover publication and write boundaries."""
import copy
import unittest
from fastapi.testclient import TestClient
import test_purchase_options as helpers
from test_checkout import ORIGIN
from sites import checkout_id
from plans import choice_id


class SiteTests(unittest.TestCase):
    setUp = helpers.PurchaseOptionTests.setUp
    tearDown = helpers.PurchaseOptionTests.tearDown
    post = helpers.PurchaseOptionTests.post
    review = helpers.PurchaseOptionTests.review
    apply = helpers.PurchaseOptionTests.apply
    state = helpers.PurchaseOptionTests.state
    preset = helpers.PurchaseOptionTests.preset
    provision = helpers.PurchaseOptionTests.provision
    save = helpers.PurchaseOptionTests.save

    def test_wlmd_mapping_is_explicit_preserved_and_cannot_be_reassigned(self):
        self.seed()
        self.site['wlmd_site_id']='  wlmd-example-101  '
        self.save('site',self.site)
        saved=self.app.state.admin.get('site',self.site['id'])
        self.assertEqual(saved['wlmd_site_id'],'wlmd-example-101')
        self.site.pop('wlmd_site_id')
        self.save('site',self.site)
        self.assertEqual(self.app.state.admin.get('site',self.site['id'])['wlmd_site_id'],'wlmd-example-101')
        response=self.post('reviews',{'kind':'site','data':dict(self.site,wlmd_site_id='another-tenant')})
        self.assertEqual(response.status_code,409,response.text)

    def test_wlmd_mapping_never_defaults_to_sticky_campaign(self):
        self.seed();self.save('site',self.site)
        self.assertNotIn('wlmd_site_id',self.app.state.admin.get('site',self.site['id']))
        from sites import Site
        from pydantic import ValidationError
        for value in ['https://example.invalid','../other','a/b','a b']:
            with self.assertRaises(ValidationError):Site.model_validate(dict(self.site,wlmd_site_id=value))

    def test_master_therapy_skeleton_records_exact_contract_with_starter_prices(self):
        from therapy_skeletons import weight_loss_skeleton
        skeleton = weight_loss_skeleton()
        products = skeleton['products']
        self.assertEqual(len(products), 16)
        self.assertEqual({p['sku'] for p in products}, {f'{t}-{m}M{s}' for t in ('SEMA','TIRZ') for m in (1,3,6,12) for s in ('','-SUB')})
        for p in products:
            self.assertEqual(p['price'],format(__import__('decimal').Decimal('249.00' if p['sku'].startswith('SEMA') else '449.00')*p['duration_months'],'.2f'))
            self.assertEqual(p['charge'], 'full_term_upfront')
            self.assertEqual(p['renewal_months'], p['duration_months'] if p['sku'].endswith('-SUB') else None)
            self.assertEqual(p['shipments_per_term'], {6:2,12:4}.get(p['duration_months']))
            self.assertEqual(p['shipment_interval'],90 if p['duration_months'] in (6,12) else None)
            self.assertEqual(p['later_shipment_charge'], '0.00')
        self.assertFalse(skeleton['ready'])
        products[0]['price'] = '123'
        self.assertEqual(weight_loss_skeleton()['products'][0]['price'],'249.00')

    def test_master_skeleton_draft_preserves_contract_and_cannot_publish(self):
        from therapy_skeletons import skeleton_draft
        draft = skeleton_draft()
        before = copy.deepcopy(self.fake.calls)
        self.save('template_editor', draft)
        saved = self.state()['templateDrafts'][0]
        self.assertEqual(saved['skeleton_id'], draft['skeleton_id'])
        self.assertEqual(len(saved['plans']), 4)
        self.assertEqual(self.state()['checkoutTemplates'], [])
        self.assertEqual(self.state()['therapySkeletons'][0]['id'], draft['skeleton_id'])
        self.assertEqual(self.fake.calls, before)
        self.save('template_editor', draft)
        self.assertEqual(len(self.state()['templateDrafts']), 1)
        for change in ({'draft':False}, {'skeleton_id':None}, {'skeleton_id':'unknown'}):
            result = self.post('reviews', {'kind':'template_editor','data':draft|change})
            self.assertEqual(result.status_code, 422, result.text)
        self.assertEqual(self.fake.calls, before)

    def seed(self):
        helpers.PurchaseOptionTests.seed(self)
        self.template = {'id':'weight-loss', 'name':'Weight Loss', 'title':'Choose your plan', 'therapy_id':'weight-loss',
            'purchase_option_ids':['monthly','quarterly'], 'enabled':True}
        self.site = {'id':'example-site','name':'Example Site','brand_id':'test-brand','campaign_id':422}
        self.save('checkout_template',self.template)

    def get_plan(self):
        return next(p for p in self.state()['planCheckouts'] if p['id']==checkout_id(self.site['id'],self.template['id']))

    def override(self, **changes):
        return {'site_id':self.site['id'],'template_id':self.template['id'],'title':'Site heading','purchase_option_ids':['monthly'],
            'payment_types':['once'],'visibility':'public','enabled':True}|changes

    def test_one_review_prepares_branded_checkouts_without_new_sku_assignment_steps(self):
        self.seed();self.save('brand',{'id':'second-brand','name':'Second site brand','campaign_id':167,'color':'#123456'})
        self.site.update(brand_id='second-brand',campaign_id=167)
        before=copy.deepcopy(self.fake.calls);review=self.review('site',self.site)
        self.assertEqual(before,self.fake.calls)
        self.assertEqual(len(review['preview']['templates']),1)
        result=self.apply(review);self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['checkouts'][0]['status'],'ready')
        plan=self.get_plan();self.assertEqual(len(plan['entries']),3);self.assertEqual(plan['visibility'],'private')
        c=TestClient(self.app,base_url=ORIGIN);self.assertEqual(c.get('/plans/'+plan['id']).status_code,401)
        self.assertEqual(c.get(plan['url']).status_code,200)
        data=c.get('/api/plans/'+plan['id']).json();self.assertEqual(data['branding']['color'],'#123456')
        self.assertEqual({e['durationMonths'] for e in data['entries']},{1,3})
        self.assertEqual(self.fake.count('/authorize_payment'),0);self.assertEqual(self.fake.count('/new_order'),0)

    def test_repeat_setup_reuses_objects_and_preserves_private_invitations(self):
        self.seed();r=self.review('site',self.site);self.assertEqual(self.apply(r).status_code,200)
        before=copy.deepcopy(self.fake.calls);url=self.get_plan()['url'];links=self.app.state.admin.records('link')
        self.assertEqual(self.apply(r).status_code,200)
        self.save('site',self.site)
        self.assertEqual(before,self.fake.calls);self.assertEqual(self.get_plan()['url'],url)
        self.assertEqual(self.app.state.admin.records('link'),links)

    def test_new_brand_and_campaign_provision_in_one_review(self):
        self.seed();self.site={'id':'new-site','name':'New site','brand_id':'new-brand','campaign_name':'New synthetic campaign','routing_template_id':422,
            'new_brand':{'id':'new-brand','name':'New brand','color':'#112233'}}
        r=self.review('site',self.site);self.assertIsNone(self.app.state.admin.get('brand','new-brand'))
        result=self.apply(r);self.assertEqual(result.status_code,200,result.text)
        site=self.state()['sites'][0];self.assertGreater(site['campaign_id'],0);self.assertEqual(site['checkouts'][0]['status'],'ready')
        self.assertEqual(self.get_plan()['brand_id'],'new-brand');self.assertIn('campaign',result.json()['created'])

    def test_updates_are_explicit_and_keep_custom_title_choices_prices_and_url(self):
        self.seed();self.save('site',self.site);self.save('site_checkout',self.override())
        before=self.get_plan();offer=next(o for o in self.state()['offers'] if o['sku']=='TIRZ-1M')
        edit={k:offer[k] for k in ('id','brand_id','sku','name','billing_models','configuration')};self.save('offer',edit|{'price':'222.00'})
        self.save('checkout_template',self.template|{'title':'Updated template title'})
        self.assertTrue(self.state()['sites'][0]['checkouts'][0]['update_available']);self.assertEqual(self.get_plan()['title'],'Site heading')
        self.save('site',self.site);after=self.get_plan();self.assertEqual(after['title'],'Site heading');self.assertEqual(after['purchase_option_ids'],['monthly'])
        self.assertEqual(after['url'],before['url']);self.assertTrue(all(len(e['options'])==1 and e['options'][0].endswith(':2') for e in after['entries']))
        self.assertEqual(next(o for o in self.state()['offers'] if o['id']==offer['id'])['price'],'222.00')
        self.assertFalse(self.state()['sites'][0]['checkouts'][0]['update_available'])

    def test_customize_uses_published_snapshot_and_cannot_add_unreviewed_choices(self):
        self.seed();self.save('site',self.site)
        self.save('purchase_option',self.monthly|{'payment_types':['once']})
        self.save('checkout_template',self.template|{'purchase_option_ids':['quarterly']})
        self.save('site_checkout',self.override(payment_types=['subscription']))
        self.assertTrue(all(e['options'][0].endswith(':3') for e in self.get_plan()['entries']))
        r=self.post('reviews',{'kind':'site_checkout','data':self.override(purchase_option_ids=['missing'])});self.assertEqual(r.status_code,422)
        r=self.post('reviews',{'kind':'plan_checkout','data':{k:v for k,v in self.get_plan().items() if k in ('id','brand_id','campaign_id','therapy_id','title','visibility','enabled','purchase_option_ids')}});self.assertEqual(r.status_code,422)

    def test_template_validation_no_invented_skus_or_duration_fallback(self):
        self.seed()
        for fields in ({'purchase_option_ids':['missing']},{'therapy_id':'missing'},{'purchase_option_ids':['monthly','monthly']}):
            self.assertEqual(self.post('reviews',{'kind':'checkout_template','data':self.template|fields}).status_code,422)
        self.save('purchase_option',self.monthly|{'skus':[]})
        self.assertEqual(self.post('reviews',{'kind':'site','data':self.site}).status_code,422)

    def test_stale_template_and_remote_catalog_preview_rejected(self):
        self.seed();r=self.review('site',self.site);self.save('checkout_template',self.template|{'title':'Changed'})
        self.assertEqual(self.apply(r).status_code,409)
        r=self.review('site',self.site);self.fake.products[self.state()['offers'][0]['product_id']]['price']='999.00'
        self.assertEqual(self.apply(r).status_code,409)

    def test_open_payment_blocks_site_and_checkout_changes(self):
        self.seed();self.save('site',self.site);plan=self.get_plan();entry=plan['entries'][0]
        child=choice_id(plan['id'],entry['sku'],entry['purchase_option_id'])
        key=self.app.state.store.create(422,entry['sku'],link_id=child);self.app.state.store.claim('new','awaiting_card',key)
        for kind,data in [('site',self.site),('site_checkout',self.override())]:
            self.assertEqual(self.apply(self.review(kind,data)).status_code,409)

    def test_uncertain_provision_blocks_duplicates_across_site_and_advanced_flows(self):
        self.seed();self.site.update(campaign_id=167);self.fake.fail_attachment=True;r=self.review('site',self.site)
        self.assertEqual(self.apply(r).status_code,502);before=copy.deepcopy(self.fake.calls)
        self.assertEqual(self.apply(r).status_code,409)
        for kind,data in [('site',self.site),('site',self.site|{'id':'different-site'}),('campaign_setup',{'brand_id':'test-brand','campaign_id':167})]:
            self.assertEqual(self.post('reviews',{'kind':kind,'data':data}).status_code,409)
        self.assertEqual(self.fake.calls,before)

    def test_site_mapping_is_stable_and_each_site_has_independent_pricing_scope(self):
        self.seed();self.save('site',self.site)
        for data in (self.site|{'id':'another-site'},self.site|{'campaign_id':167},self.site|{'brand_id':'other'}):
            self.assertIn(self.post('reviews',{'kind':'site','data':data}).status_code,(409,422))

    def test_uncertain_new_campaign_cannot_be_recreated_from_advanced_setup(self):
        self.seed();request={k:v for k,v in self.site.items() if k!='campaign_id'}|{'campaign_name':'Held site campaign'}
        self.fake.deny_new_campaign=True
        self.assertEqual(self.apply(self.review('site',request)).status_code,502)
        before=copy.deepcopy(self.fake.calls)
        self.assertEqual(self.post('reviews',{'kind':'campaign_setup','data':{'brand_id':'test-brand','name':'Held site campaign','template_id':422}}).status_code,409)
        self.assertEqual(self.fake.calls,before)

    def test_readiness_rechecks_gateway_and_does_not_change_legacy_links(self):
        self.seed();legacy=copy.deepcopy(self.state()['links']);self.save('site',self.site)
        self.assertEqual(self.state()['links'],legacy)
        original=self.fake.detail
        self.fake.detail=lambda path: (original(path)|{'account_id':180}) if '/profiles/' in path else original(path)
        self.assertEqual(self.state()['sites'][0]['checkouts'][0]['status'],'incomplete')

    def test_owner_and_csrf_required(self):
        self.seed();outsider=TestClient(self.app,base_url=ORIGIN)
        self.assertEqual(outsider.post('/api/admin/reviews',json={'kind':'site','data':self.site}).status_code,401)
        self.assertEqual(self.client.post('/api/admin/reviews',json={'kind':'site','data':self.site}).status_code,403)

    def test_inaccessible_campaign_marks_incomplete_without_losing_admin_workspace(self):
        self.seed();self.save('site',self.site)
        def unavailable(path):raise RuntimeError('Synthetic API access failure')
        self.fake.detail=unavailable
        response=self.client.get('/api/admin/state');self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['sites'][0]['checkouts'][0]['status'],'incomplete')



    def editor(self, **changes):
        plans = [{k:v for k,v in self.app.state.admin.get('purchase_option', p).items() if k != 'revision'} for p in ['monthly','quarterly']]
        return {'id':'weight-loss','name':'Weight Loss','title':'Choose your plan','therapy_id':'weight-loss','plans':plans} | changes

    def test_editor_saves_complete_template_without_touching_shared_plans(self):
        self.seed(); before=copy.deepcopy(self.app.state.admin.get('purchase_option','monthly'))
        payload=self.editor(); payload['plans'][0]['name']='Monthly care'
        review=self.review('template_editor',payload)
        self.assertEqual(self.app.state.admin.get('purchase_option','monthly'),before)
        self.assertEqual(review['preview']['stickyWrites'],[])
        self.assertEqual(self.apply(review).status_code,200)
        self.assertEqual(self.app.state.admin.get('purchase_option','monthly'),before)
        template=self.app.state.admin.get('checkout_template','weight-loss')
        self.assertTrue(all(p.startswith('tpl-') for p in template['purchase_option_ids']))
        self.save('site',self.site)
        self.assertEqual(self.state()['sites'][0]['checkouts'][0]['status'],'ready')

    def test_editor_draft_keeps_published_template_and_site_unchanged(self):
        self.seed();self.save('site',self.site)
        before=self.get_plan(); published=self.app.state.admin.get('checkout_template','weight-loss')
        payload=self.editor(draft=True);payload['plans'][0]['skus']=[]
        self.save('template_editor',payload)
        self.assertEqual(self.app.state.admin.get('checkout_template','weight-loss'),published)
        self.assertEqual(self.get_plan(),before)
        self.assertEqual(len(self.state()['templateDrafts']),1)
        r=self.post('reviews',{'kind':'template_editor','data':payload|{'draft':False}})
        self.assertEqual(r.status_code,422);self.assertIn('choose at least one product',r.text)
        self.save('template_editor',self.editor())
        self.assertEqual(self.state()['templateDrafts'],[])

    def test_editor_creates_new_therapy_draft_without_enabling_empty_checkout(self):
        self.seed();payload={'id':'new-template','name':'New therapy','title':'Choose a plan','therapy_id':'new-therapy',
            'new_therapy':{'id':'new-therapy','name':'New therapy','treatments':[{'id':'example','name':'Example'}]},'plans':[],'draft':True}
        self.save('template_editor',payload)
        self.assertIsNone(self.app.state.admin.get('checkout_template','new-template'))
        self.assertEqual(self.app.state.admin.get('therapy','new-therapy')['name'],'New therapy')
        self.assertEqual(self.state()['templateDrafts'][0]['new_therapy']['name'],'New therapy')

    def test_editor_rejects_mismatch_and_stale_review_without_partial_saves(self):
        self.seed();payload=self.editor();payload['plans'][0]['duration_months']=12
        r=self.post('reviews',{'kind':'template_editor','data':payload})
        self.assertEqual(r.status_code,422)
        self.assertFalse(any(p['id'].startswith('tpl-') for p in self.app.state.admin.records('purchase_option')))
        review=self.review('template_editor',self.editor())
        self.save('template_editor',self.editor(draft=True))
        self.assertEqual(self.apply(review).status_code,409)

    def test_editor_plan_ids_survive_reordering_and_customized_site_updates(self):
        self.seed();self.save('template_editor',self.editor());self.save('site',self.site)
        template=self.app.state.admin.get('checkout_template','weight-loss');ids=template['purchase_option_ids']
        self.save('site_checkout',self.override(purchase_option_ids=[ids[0]]))
        old_url=self.get_plan()['url']
        plans=[{k:v for k,v in self.app.state.admin.get('purchase_option',p).items() if k!='revision'} for p in reversed(ids)]
        self.save('template_editor',self.editor(plans=plans,title='Updated'))
        self.assertEqual(self.app.state.admin.get('checkout_template','weight-loss')['purchase_option_ids'],list(reversed(ids)))
        self.assertEqual(self.get_plan()['url'],old_url)
        self.save('site',self.site)
        self.assertEqual(self.get_plan()['purchase_option_ids'],[ids[0]])
        self.assertEqual(self.get_plan()['purchase_options'][0]['duration_months'],1)

    def test_site_remembers_reviewed_connection_and_paused_is_not_ready(self):
        self.seed();self.save('site',self.site|{'remember_connection':True})
        self.assertEqual(self.state()['siteDefaults']['routing_template_id'],422)
        self.save('site_checkout',self.override(enabled=False))
        self.assertEqual(self.state()['sites'][0]['checkouts'][0]['status'],'paused')


if __name__=='__main__':unittest.main()
