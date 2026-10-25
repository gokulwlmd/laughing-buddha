import copy
import json
import unittest
from pathlib import Path
import test_fortifyhp_setup as fixtures
from fortifyhp_nad_test import NadSetup, SKU, SOURCE_ID, SOURCE_SKU, PUBLIC_PLAN
from fortifyhp_publish_api import build_configuration
from import_wellness_masters import prepare as masters
from catalog_refill_policies import source_products, proposed_policy
from external_fulfillment import fortifyhp_prepaid_supported, fortifyhp_order_scope
from test_external_fulfillment import FortifyCatalog

class NadSetupTests(unittest.TestCase):
    setUpBase=fixtures.FortifySetupTests.setUp
    tearDown=fixtures.FortifySetupTests.tearDown
    def setUp(self):
        self.setUpBase();self.setup.apply()
        admin=self.app.state.admin
        for (k,i),v in masters({}).items():admin.put(k,i,v)
        p=next(p for p in source_products() if SKU==p['sku']+'-SUB')
        admin.put('refill_policy',SKU,proposed_policy(p,SKU))
        self.fake.products[SOURCE_ID]=dict(self.fake.products[33367],id=SOURCE_ID,sku=SOURCE_SKU,name='NAD Injection: NAD+ 12 month')
        old=self.fake.detail
        def detail(path):
            if path=='/api/v2/billing_models/4':return next(m for m in self.fake.models() if m['id']==4)
            value=old(path)
            if path=='/api/v2/offers/423':value['products'].append({'id':SOURCE_ID})
            return value
        self.fake.detail=detail
        self.manifest=Path(self.temp.name)/'site-api-publications.json'
        self.manifest.write_text(json.dumps({'version':1,'sites':[build_configuration(admin).model_dump(mode='json')]}))
        self.nad=NadSetup.__new__(NadSetup);self.nad.admin=admin;self.nad.api=self.fake
        self.nad.path=Path(self.temp.name)/'nad-journal.json';self.nad.state={'run_id':'offline','operations':{}}
        with admin.store.db() as db:self.before={(k,i):v for k,i,v in db.execute('SELECT kind,id,data FROM admin_config')}

    def test_additive_publish_and_replay_without_orders(self):
        products=copy.deepcopy(self.fake.products);offer_ids=list(self.fake.campaign_offers[195])
        result=self.nad.apply()
        self.assertEqual(result['orders_created'],0)
        self.assertEqual(self.fake.campaign_offers[195][:-1],offer_ids)
        self.assertTrue(all(self.fake.products[k]==v for k,v in products.items()))
        with self.app.state.admin.store.db() as db:after={(k,i):v for k,i,v in db.execute('SELECT kind,id,data FROM admin_config')}
        self.assertTrue(all(after[k]==v for k,v in self.before.items()))
        plan=self.app.state.admin.get('plan_checkout',PUBLIC_PLAN)
        self.assertEqual(plan['entries'][0]['sku'],SKU)
        self.assertEqual(plan['template_snapshot']['masters'][0]['product_setup']['shipment_days'],[0,90,180,270])
        self.assertEqual(len(json.loads(self.manifest.read_text())['sites'][0]['therapies']),5)
        writes=len([x for x in self.fake.calls if x[0]!='GET' and not x[1].endswith('/calculate')])
        self.assertEqual(self.nad.apply(),result)
        self.assertEqual(writes,len([x for x in self.fake.calls if x[0]!='GET' and not x[1].endswith('/calculate')]))
        self.assertFalse(any('new_order' in p or 'authorize_payment' in p for _,p,_ in self.fake.calls))

    def test_uncertain_product_is_not_recreated(self):
        self.nad.prepare();self.nad.state['operations']['product:'+SKU]={'status':'pending','body_hash':'unknown'}
        before=len(self.fake.products)
        with self.assertRaisesRegex(ValueError,'Reconcile'):self.nad.apply()
        self.assertEqual(len(self.fake.products),before)

    def test_scope_does_not_enable_other_wellness_plans(self):
        fake=FortifyCatalog();fake.product['sku']=SKU
        self.assertTrue(fortifyhp_prepaid_supported(fake.campaign,fake.product,fake.offer))
        self.assertTrue(fortifyhp_order_scope(195,269,SKU))
        for sku in ('NAD-INJ-12M','NAD-INJ-6M-SUB','GLUTA-12M-SUB'):
            fake.product['sku']=sku
            self.assertFalse(fortifyhp_prepaid_supported(fake.campaign,fake.product,fake.offer))
        self.assertFalse(fortifyhp_order_scope(422,269,SKU))

import test_wellness_refills as wellness
import test_member_portal as portal
from test_member_fortify_claims import fortify_fixture
from datetime import datetime, timedelta, timezone

class FortifyNadClaimTests(wellness.WellnessClaimTests):
    def setUp(self):
        portal.MemberPortalTests.setUp(self)
        self.fake,self.sku=wellness.configure_wellness_fixture(self.app)
        fortify_fixture(self.fake)
        admin=self.app.state.admin
        for kind,key in [('site','site-a'),('brand','brand-a'),('plan_checkout','plan-a'),('link','member-link-a')]:
            row=admin.get(kind,key);row['campaign_id']=195
            if kind=='plan_checkout':row['payment_test_only']=False
            admin.put(kind,key,row)
        with self.app.state.store.db() as db:db.execute("UPDATE checkouts SET campaign=195 WHERE order_id='9001'")
        now=datetime(2026,10,22,19,4,34,tzinfo=timezone.utc)+timedelta(days=70)
        self.service.clock=self.service.provider.wall_clock=lambda:now.timestamp()
        self.enroll();self.care_path=self.base+'/orders/9001/care-plan'

    def test_real_order_shape_claims_zero_with_no_additional_intake(self):
        self.assertEqual(self.claim(90).status_code,409)
        self.complete_initial()
        result=self.claim(90)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['claim']['amount'],'0.00')
        self.assertEqual(self.fake.orders['9002']['products'][0]['sku'],SKU)
        self.assertEqual(self.client.get(self.base+'/intakes/9002',headers=self.patient_headers).status_code,409)
        self.assertEqual(self.claim(90,'different-key').status_code,200)
        self.assertEqual(len([p for _,p,_ in self.fake.calls if p.endswith('/order_force_bill')]),1)

for parent in FortifyNadClaimTests.__mro__[1:]:
    for name in vars(parent):
        if name.startswith('test_') and name not in vars(FortifyNadClaimTests):setattr(FortifyNadClaimTests,name,None)
