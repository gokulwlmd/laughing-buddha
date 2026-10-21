"""QA regression cases for usability recovery, billing safety and publication readiness."""
import copy
import json
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
import test_admin as admin_helpers
import test_checkout as checkout_helpers
from app import create_app

class AdminRegressions(unittest.TestCase):
    setUp=admin_helpers.AdminTests.setUp
    tearDown=admin_helpers.AdminTests.tearDown
    post=admin_helpers.AdminTests.post
    review=admin_helpers.AdminTests.review
    apply=admin_helpers.AdminTests.apply
    seed=admin_helpers.AdminTests.seed
    link_data=admin_helpers.AdminTests.link_data
    publish=admin_helpers.AdminTests.publish

    def test_dollar_prefixed_name_is_literal_and_internal_refs_resolve(self):
        self.seed();r=self.review('offer',{'brand_id':'test-brand','sku':checkout_helpers.SKU,'name':'$9 intro offer','price':'9.00','billing_models':[2]})
        result=self.apply(r);self.assertEqual(result.status_code,200,result.text)
        offer=next(iter(self.fake.offers.values()));self.assertEqual(offer['name'],'$9 intro offer')
        self.assertIsInstance(offer['products'][0]['id'],int)

    def test_refreshed_new_offer_draft_does_not_become_an_edit(self):
        self.seed();r=self.review('offer',{'brand_id':'test-brand','sku':checkout_helpers.SKU,'name':'Fresh offer','price':'3.00','billing_models':[2]})
        refreshed=self.post('reviews/'+r['id']+'/refresh',{})
        self.assertEqual(refreshed.status_code,200,refreshed.text)
        self.assertEqual(self.fake.count('/products'),0)
        self.assertEqual(self.apply(refreshed.json()).status_code,200)
        self.assertEqual(self.fake.count('/products'),1)

    def test_refresh_uses_current_local_state_and_requires_explicit_approval(self):
        first=self.review('brand',{'id':'first-brand','name':'First'})
        self.apply(self.review('brand',{'id':'other-brand','name':'Other'}))
        self.assertEqual(self.apply(first).status_code,409)
        refreshed=self.post('reviews/'+first['id']+'/refresh',{});self.assertEqual(refreshed.status_code,200)
        self.assertEqual(len(self.client.get('/api/admin/state').json()['brands']),1)
        self.assertEqual(self.apply(refreshed.json()).status_code,200)

    def test_discarded_review_is_terminal_and_does_not_write_config(self):
        r=self.review('brand',{'id':'draft-brand','name':'Draft'})
        self.assertEqual(self.post('reviews/'+r['id']+'/discard',{}).status_code,200)
        self.assertEqual(self.apply(r).status_code,409)
        self.assertEqual(self.post('reviews/'+r['id']+'/refresh',{}).status_code,409)
        self.assertEqual(self.client.get('/api/admin/state').json()['brands'],[])

    def test_uncertain_write_cannot_be_refreshed_or_discarded(self):
        self.seed();r=self.review('offer',{'brand_id':'test-brand','sku':checkout_helpers.SKU,'name':'Held','price':'3.00','billing_models':[2]})
        self.fake.fail_offer=True;self.assertEqual(self.apply(r).status_code,502)
        self.assertEqual(self.post('reviews/'+r['id']+'/refresh',{}).status_code,409)
        self.assertEqual(self.post('reviews/'+r['id']+'/discard',{}).status_code,409)
        self.assertEqual(self.fake.count('/products'),1)

    def test_refresh_and_discard_require_csrf_and_owner(self):
        r=self.review('brand',{'id':'draft-brand','name':'Draft'})
        for action in ('refresh','discard'):
            self.assertEqual(self.client.post('/api/admin/reviews/'+r['id']+'/'+action,json={}).status_code,403)
            outsider=TestClient(self.app,base_url=checkout_helpers.ORIGIN)
            self.assertEqual(outsider.post('/api/admin/reviews/'+r['id']+'/'+action,json={}).status_code,401)

    def test_unready_payment_route_cannot_be_published_but_can_be_saved_inactive(self):
        self.seed();original=self.fake.detail
        def detail(path):
            d=original(path)
            if '/profiles/' in path:d['account_id']=180
            return d
        self.fake.detail=detail
        self.assertEqual(self.post('reviews',{'kind':'link','data':self.link_data()}).status_code,422)
        r=self.review('link',self.link_data()|{'enabled':False});self.assertEqual(self.apply(r).status_code,200)
        self.assertEqual(self.client.get('/c/test-link').status_code,404)

    def test_trial_offer_cannot_be_published_as_ready(self):
        self.seed();self.fake.prepaid=True
        r=self.post('reviews',{'kind':'link','data':self.link_data()});self.assertEqual(r.status_code,422)
        self.assertIn('not ready',r.text)

    def test_inspection_reports_exact_products_and_base_prices(self):
        self.fake.duplicate=True
        r=self.client.get('/api/admin/inspect',params={'campaign_id':422,'sku':checkout_helpers.SKU})
        self.assertEqual(r.status_code,200)
        self.assertEqual({x['productId'] for x in r.json()['options']},{54537,54538})
        self.assertTrue(all(x['basePrice']=='2.00' for x in r.json()['options']))
        self.assertNotIn('NEVER_EXPOSE_THIS',r.text)

    def test_template_is_owner_only_and_does_not_expose_gateway_credentials(self):
        r=self.client.get('/api/admin/campaign-template',params={'campaign_id':422});self.assertEqual(r.status_code,200)
        self.assertEqual(r.json()['gateway_id'],254);self.assertNotIn('NEVER_EXPOSE_THIS',r.text)
        outsider=TestClient(self.app,base_url=checkout_helpers.ORIGIN)
        self.assertEqual(outsider.get('/api/admin/campaign-template?campaign_id=422').status_code,401)

    def test_clone_preserves_documented_shipping_weight_and_tax_fields(self):
        self.seed();original=self.fake.detail
        def detail(path):
            p=original(path)
            if path.endswith('/products/54537'):
                p.update({'weight':'1.50','weight_unit':{'id':2},'tax_code':'TAX123','shipping_restrictions':[{'country_id':223,'values':['CA']}],'is_signature_confirm':1})
            return p
        self.fake.detail=detail
        r=self.review('offer',{'brand_id':'test-brand','sku':checkout_helpers.SKU,'name':'Shipping price','price':'3.00','billing_models':[2]})
        product=r['preview']['stickyWrites'][0]['body']
        self.assertEqual(product['weight'],'1.50');self.assertEqual(product['weight_unit_id'],2)
        self.assertEqual(product['tax_code'],'TAX123');self.assertEqual(product['is_signature_confirm'],1)
        self.assertEqual(product['shipping_restrictions'],[{'country_id':223,'values':['CA']}])

    def test_unsupported_shipping_restriction_is_rejected_before_any_write(self):
        self.seed();original=self.fake.detail
        def detail(path):
            p=original(path)
            if path.endswith('/products/54537'):p['shipping_restrictions']=[{'unknown':'format'}]
            return p
        self.fake.detail=detail
        r=self.post('reviews',{'kind':'offer','data':{'brand_id':'test-brand','sku':checkout_helpers.SKU,'name':'Shipping','price':'3.00','billing_models':[2]}})
        self.assertEqual(r.status_code,422);self.assertEqual(self.fake.count('/products'),0)

    def test_expired_review_is_not_approved_without_refresh(self):
        r=self.review('brand',{'id':'old-brand','name':'Old'})
        with self.app.state.store.db() as db:db.execute('UPDATE admin_reviews SET created=0 WHERE id=?',(r['id'],))
        self.assertEqual(self.apply(r).status_code,409)
        refreshed=self.post('reviews/'+r['id']+'/refresh',{});self.assertEqual(refreshed.status_code,200)
        self.assertEqual(self.apply(refreshed.json()).status_code,200)

    def test_qa_control_routes_are_not_in_the_production_application(self):
        self.assertEqual(self.client.get('/__qa/state').status_code,404)
        self.assertEqual(self.client.post('/__qa/control',json={}).status_code,404)

class PaymentRegressions(unittest.TestCase):
    setUp=checkout_helpers.CheckoutTests.setUp
    tearDown=checkout_helpers.CheckoutTests.tearDown
    post=checkout_helpers.CheckoutTests.post
    quote=checkout_helpers.CheckoutTests.quote
    authorize=checkout_helpers.CheckoutTests.authorize
    capture=checkout_helpers.CheckoutTests.capture

    def test_resume_returns_existing_secret_without_new_authorization(self):
        original=self.authorize().json()
        r=self.post('resume',{});self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['intentId'],original['intentId']);self.assertEqual(r.json()['clientSecret'],original['clientSecret'])
        self.assertEqual(r.json()['contact'],checkout_helpers.CONTACT);self.assertEqual(self.fake.count('/authorize_payment'),1)

    def test_resume_enforces_csrf_and_attempt_binding(self):
        self.authorize()
        self.assertEqual(self.client.post('/api/resume',params=self.params,json={}).status_code,403)
        r=self.client.post('/api/resume',params=self.params,headers=self.headers|{'X-Checkout-Attempt':'other'},json={})
        self.assertEqual(r.status_code,409);self.assertEqual(self.fake.count('/authorize_payment'),1)

    def test_restart_loses_secret_and_holds_attempt_without_reauthorizing(self):
        self.authorize();other=create_app(self.settings,self.fake)
        client=TestClient(other,base_url=checkout_helpers.ORIGIN)
        client.cookies.update(self.client.cookies)
        r=client.post('/api/resume',params=self.params,headers=self.headers,json={})
        self.assertEqual(r.status_code,409);self.assertEqual(self.fake.count('/authorize_payment'),1)
        self.assertEqual(other.state.store.read(self.headers['X-Checkout-Attempt'])['status'],'awaiting_card')

    def test_route_change_prevents_resume(self):
        self.authorize();self.fake.link_gateway=165
        self.assertEqual(self.post('resume',{}).status_code,409)
        self.assertEqual(self.fake.count('/authorize_payment'),1)

    def test_uncertain_capture_cannot_resume_or_reauthorize(self):
        self.authorize();self.fake.capture_code='101';self.capture()
        self.assertEqual(self.post('resume',{}).status_code,409)
        self.assertEqual(self.post('authorize',{'quote_id':'old'}).status_code,409)
        self.assertEqual(self.fake.count('/new_order'),1)

    def test_expired_quote_does_not_create_authorization(self):
        q=self.quote().json();key=self.headers['X-Checkout-Attempt'];row=self.app.state.store.read(key)
        quote=json.loads(row['quote']);quote['expires']=0
        self.app.state.store.claim('new','new',key,quote=json.dumps(quote))
        r=self.post('authorize',{'quote_id':q['id']});self.assertEqual(r.status_code,409)
        self.assertEqual(self.fake.count('/authorize_payment'),0)

    def test_non_numeric_phone_fails_before_quote_or_authorization(self):
        r=self.post('quote',{'contact':checkout_helpers.CONTACT|{'phone':'abcdefghijk'},'selection':'706:54537:2','shipping_id':2})
        self.assertEqual(r.status_code,422);self.assertEqual(self.fake.count('/authorize_payment'),0)

    def test_recurring_consent_is_recorded_on_the_owned_quote(self):
        self.fake.recurring=True;self.assertEqual(self.authorize(consent=True,selection='706:54537:3').status_code,200)
        q=json.loads(self.app.state.store.read(self.headers['X-Checkout-Attempt'])['quote'])
        self.assertTrue(q['recurring_consent']);self.assertGreater(q['consented_at'],0)

if __name__=='__main__':unittest.main()
