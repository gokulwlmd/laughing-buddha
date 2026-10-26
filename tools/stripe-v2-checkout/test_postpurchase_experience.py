"""Offline post-purchase contracts; no real provider requests."""
import json, os, unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock
from fastapi import HTTPException
from member_portal.upsells import PostPurchaseOffers, BuyOffer, key
from member_portal.intake_templates import get_template
from patient_demo.app import visible, IntakeTemplate
from test_sticky_membership import StickyMembershipTests

class HandoffTests(StickyMembershipTests):
    def test_single_use_site_bound_handoff(self):
        result=self.setup();token=result['portal_handoff']
        self.assertNotIn('access_token',result)
        with self.assertRaises(HTTPException):self.service.consume_handoff('site-b',token)
        auth=self.service.consume_handoff('site-a',token)
        self.assertEqual(self.client.get(self.base+'/me',headers={'Authorization':'Bearer '+auth['access_token']}).status_code,200)
        with self.assertRaises(HTTPException):self.service.consume_handoff('site-a',token)
    def test_expired_handoff(self):
        token=self.setup()['portal_handoff'];now=self.service.clock();self.service.clock=lambda:now+1801
        with self.assertRaises(HTTPException):self.service.consume_handoff('site-a',token)
    def test_revoked_session_rejects_handoff(self):
        token=self.setup()['portal_handoff'];self.remote.active=False
        with self.assertRaises(HTTPException):self.service.consume_handoff('site-a',token)
    def test_handoff_expiration_does_not_outlive_sticky_session(self):
        from datetime import datetime, timezone
        self.setup()
        expires=self.service.clock()+90
        self.remote.members[self.email()]['identity']['token_expires_at']=datetime.fromtimestamp(expires,timezone.utc).isoformat()
        result=self.setup()
        self.assertEqual(datetime.fromisoformat(result['handoff_expires_at'].replace('Z','+00:00')).timestamp(),expires)

class QuestionnaireTests(unittest.TestCase):
    def test_reference_schema_preserves_branches_without_ssn(self):
        with patch.dict(os.environ,{'WEIGHT_LOSS_INTAKE_SOURCE':'coreage'}):
            template=get_template('weight-loss',sku='SEMA-12M-SUB')
            checkin=get_template('weight-loss',sku='SEMA-12M-SUB',kind='checkin')
        parsed=IntakeTemplate.model_validate(template).model_dump();qs={q['id']:q for q in parsed['questions']}
        self.assertEqual(len(qs),67);self.assertEqual(parsed['version'],'coreage-reference-2026-10-26')
        self.assertFalse(visible(qs['ca_545'],{'ca_538':'No'}));self.assertTrue(visible(qs['ca_545'],{'ca_538':'Yes'}))
        self.assertFalse(visible(qs['ca_252'],{}));self.assertTrue(visible(qs['ca_252'],{'ca_250':['History of kidney failure']}))
        self.assertNotIn('ssn',json.dumps(parsed).lower());self.assertLess(len(checkin['questions']),20)

class OfferTests(unittest.TestCase):
    def setUp(self):
        self.records={};self.now=1000
        self.admin=SimpleNamespace(get=lambda kind,id:self.records.get((kind,id)),put=lambda kind,id,data:self.records.__setitem__((kind,id),dict(data)),api=Mock())
        self.store=Mock();self.store.create.return_value='attempt-2';self.store.claim.return_value=True
        self.order={'site_id':'a','order_id':'100','sku':'SEMA-1M','customer_id':'200'}
        self.source={'payment_status':'paid','gateway_id':'1','customer_id':'200','shipping_address':{},'customer':{'email':'synthetic@example.test'}}
        self.s=SimpleNamespace(admin=self.admin,store=self.store,receipt_order=lambda r:(self.order,{}),clock=lambda:self.now,provider=Mock(),sync=Mock())
        self.service=PostPurchaseOffers(self.s)
        self.q={'amount':100,'total':'1.00','currency':'USD','fingerprint':'unchanged','gatewayId':1,'selection':'1:2:3','campaignId':429,'sku':'METFORM-1M','shippingId':None,'option':{'offerId':1,'productId':2,'billingModelId':3}}
        self.selected={'plan_id':'target','checkout_id':'p','sku':'METFORM-1M'}
        self.service.choices=lambda site:[self.selected]
        self.service.context=lambda site,sel:({'id':'link'}, {'gatewayId':1},'1:2:3')
        self.records['postpurchase_settings','a']={'enabled':True,'plan_ids':['target'],'placements':['thank_you']}
        self.token='synthetic-quote-token-0001'
        self.records['postpurchase_quote',key(self.token)]={'site_id':'a','source_order':'100','plan_id':'target','shipping_address':{},'placement':'thank_you','expires':2000,'quote':self.q,'link_id':'link'}
        self.s.provider.read_order.return_value=self.source
        self.receipt={'contact':'{}'};self.body=BuyOffer(quote_id=self.token,confirmed=True)
        self.env=patch.dict(os.environ,{'STICKY_CARD_ON_FILE_VERIFIED_GATEWAYS':'1'});self.env.start()
        self.quote=patch('member_portal.upsells.quote',return_value=dict(self.q));self.quote.start()
    def tearDown(self):self.env.stop();self.quote.stop()
    def test_timeout_cannot_charge_again(self):
        self.admin.api.call.side_effect=TimeoutError()
        first=self.service.buy(self.receipt,self.body,'127.0.0.1');self.assertEqual(first['status'],'needs_review')
        self.assertEqual(self.service.buy(self.receipt,self.body,'127.0.0.1'),first);self.assertEqual(self.admin.api.call.call_count,1)
        payload=self.admin.api.call.call_args.args[2]
        self.assertEqual(payload['initializeNewSubscription'],1);self.assertEqual(payload['previousOrderId'],'100');self.assertEqual(payload['offers'][0]['step_num'],2)
        self.assertNotIn('creditCardNumber',payload)
    def test_unverified_gateway_no_write(self):
        with patch.dict(os.environ,{'STICKY_CARD_ON_FILE_VERIFIED_GATEWAYS':''}):
            with self.assertRaises(HTTPException):self.service.buy(self.receipt,self.body,'127.0.0.1')
        self.admin.api.call.assert_not_called()
    def test_cross_site_expiry_disabled_confirmation(self):
        self.order['site_id']='other'
        with self.assertRaises(HTTPException):self.service.buy(self.receipt,self.body,'127.0.0.1')
        self.order['site_id']='a';self.now=2001
        with self.assertRaises(HTTPException):self.service.buy(self.receipt,self.body,'127.0.0.1')
        self.now=1000;self.records['postpurchase_settings','a']['enabled']=False
        with self.assertRaises(HTTPException):self.service.buy(self.receipt,self.body,'127.0.0.1')
        self.records['postpurchase_settings','a']['enabled']=True
        with self.assertRaises(HTTPException):self.service.buy(self.receipt,BuyOffer(quote_id=self.token,confirmed=False),'127.0.0.1')
        self.admin.api.call.assert_not_called()
    def test_changed_price_and_refund_no_write(self):
        self.source['payment_status']='refunded'
        with self.assertRaises(HTTPException):self.service.buy(self.receipt,self.body,'127.0.0.1')
        self.source['payment_status']='paid'
        with patch('member_portal.upsells.quote',return_value={**self.q,'amount':200}):
            with self.assertRaises(HTTPException):self.service.buy(self.receipt,self.body,'127.0.0.1')
        self.admin.api.call.assert_not_called()
