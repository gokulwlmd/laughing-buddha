"""Offline profile reuse, consent-by-confirmation and verification boundaries."""
import json
import unittest
from copy import deepcopy
from fastapi import HTTPException
from patient_demo.app import IntakePatch, IntakeSubmit
from patient_demo.provider import get_sample_answers
from member_portal.intake_templates import get_template
import test_member_portal as fixtures


class AnswerProfileTests(unittest.TestCase):
    setUp = fixtures.MemberPortalTests.setUp
    tearDown = fixtures.MemberPortalTests.tearDown
    post_owner = fixtures.MemberPortalTests.post_owner
    enroll = fixtures.MemberPortalTests.enroll

    def prepare(self, submit=True):
        self.enroll()
        self.order = self.service.order_record('site-a', '9001')
        with self.service.db() as db:
            self.patient = dict(db.execute('SELECT * FROM member_patients WHERE site_id=?', ('site-a',)).fetchone())
        form = self.service.initial_intake(self.order, self.patient)
        answers = get_sample_answers('weight-loss'); answers.pop('demo_confirmation')
        self.service.modify_initial(self.order, IntakePatch(revision=form['revision'], answers=answers), self.patient)
        if submit:
            self.service.modify_initial(self.order, IntakeSubmit(revision=1), self.patient, True)
        other = dict(self.order, order_id='9002')
        with self.service.db() as db:
            db.execute('INSERT INTO member_orders SELECT site_id,?,customer_id,attempt_id,therapy_id,sku,snapshot,payload,synced FROM member_orders WHERE order_id=?', ('9002', '9001'))
            db.execute('INSERT INTO member_grants SELECT site_id,?,patient_id,created,source FROM member_grants WHERE order_id=?', ('9002', '9001'))
        return other

    def test_stable_reused_mutable_requires_confirmation_and_drafts_resume(self):
        other = self.prepare()
        form = self.service.initial_intake(other, self.patient)
        self.assertEqual(form['answers'], {'height_inches': 68})
        self.assertEqual(form['reused_fields'], ['height_inches'])
        allergy = next(q for q in form['template']['questions'] if q['id'] == 'allergies')
        self.assertEqual(allergy['reuse_status'], 'confirm')
        self.assertIn('No known', allergy['saved_value'])
        with self.assertRaises(HTTPException) as error:
            self.service.modify_initial(other, IntakeSubmit(revision=0), self.patient, True)
        self.assertIn('allergies', error.exception.detail['question_ids'])
        changed = self.service.modify_initial(other, IntakePatch(revision=0, answers={'height_inches': 69, 'allergies': allergy['saved_value']}), self.patient)
        self.assertEqual(self.service.initial_intake(other, self.patient)['answers'], changed['answers'])
        # HTTP response schema retains the UI metadata, without provider refs.
        public = self.client.get(self.base+'/intakes/9002', headers=self.patient_headers).json()
        self.assertEqual(next(q for q in public['template']['questions'] if q['id']=='allergies')['reuse_status'], 'confirm')

    def test_drafts_guest_receipts_and_other_sites_cannot_seed_profile(self):
        other = self.prepare(False)
        self.assertEqual(self.service.initial_intake(other, self.patient)['answers'], {})
        self.service.modify_initial(self.order, IntakeSubmit(revision=1), self.patient, True)
        template = get_template('weight-loss', sku=self.order['sku'])
        with self.service.db() as db:
            for order, patient in [(other, dict(self.patient, _reuse_allowed=False)),
                                   (dict(other, site_id='site-b'), self.patient),
                                   (other, {'id':'another-patient'})]:
                self.assertEqual(self.service.answer_profile.seed(db, order, patient, template)[1], {})

    def test_semantic_id_version_expiry_and_test_isolation(self):
        other = self.prepare()
        template = get_template('weight-loss', sku=self.order['sku'])
        question = next(q for q in template['questions'] if q['id']=='height_inches')
        question.update(id='provider-height-id', reuse_key='patient.height_inches', reuse_policy='stable', reuse_version='1')
        with self.service.db() as db:
            self.assertEqual(self.service.answer_profile.seed(db, other, self.patient, template)[1], {'provider-height-id':68})
            question['reuse_version']='2'
            self.assertEqual(self.service.answer_profile.seed(db, other, self.patient, template)[1], {})
            question.update(reuse_version='1', reuse_max_age_days=0)
            self.service.clock = lambda: fixtures.NOW+1
            self.assertEqual(self.service.answer_profile.seed(db, other, self.patient, template)[1], {})
            raw=json.loads(other['payload']);raw['test_order']=not bool(raw.get('test_order'))
            other['payload']=json.dumps(raw)
            question.pop('reuse_max_age_days')
            self.assertEqual(self.service.answer_profile.seed(db, other, self.patient, template)[1], {})

    def test_verification_only_from_backend_expires_and_cannot_be_forged(self):
        other=self.prepare()
        template=get_template('weight-loss',sku=self.order['sku'])
        template['questions']=[dict(id='ssn-check', section_id='health', type='text', label='Identity check', required=True,
            reuse_key='identity.ssn_verified', reuse_version='1', reuse_policy='verified')]
        profile=self.service.answer_profile
        with self.service.db() as db:
            with self.assertRaises(HTTPException):
                profile.validate(db, other, self.patient, template, incoming={'ssn-check':'verified'}, answers={})
        profile.record_verification(site_id='site-a',patient_id=self.patient['id'],key='identity.ssn_verified',version='1',status='verified',
            provider='offline-test',reference='opaque-test-reference',verified_at=fixtures.NOW,expires_at=fixtures.NOW+60)
        with self.service.db() as db:
            seeded, answers=profile.seed(db,other,self.patient,template)
            self.assertEqual(answers,{'ssn-check':'verified'})
            self.assertNotIn('opaque-test-reference',json.dumps(seeded))
            profile.validate(db,other,self.patient,seeded,submit=True,answers=answers)
            self.service.clock=lambda:fixtures.NOW+61
            with self.assertRaises(HTTPException):profile.validate(db,other,self.patient,seeded,submit=True,answers=answers)
            self.assertEqual(profile.seed(db,other,self.patient,template)[1],{})

    def test_policy_migration_updates_existing_enabled_claims_once(self):
        from refill_rules import migrate_claim_window
        admin=self.app.state.admin
        for kind in ('refill_policy','site_refill_policy'):
            admin.put(kind,'policy-test',{'included_refills_enabled':True,'claim_window_days':10,'revision':4})
        with self.service.db() as db:db.execute('DELETE FROM member_policy_migrations')
        migrate_claim_window(self.service.store)
        for kind in ('refill_policy','site_refill_policy'):
            self.assertEqual(admin.get(kind,'policy-test')['claim_window_days'],20)
            self.assertEqual(admin.get(kind,'policy-test')['revision'],5)
        admin.put('site_refill_policy','policy-test',{'included_refills_enabled':True,'claim_window_days':25,'revision':6})
        migrate_claim_window(self.service.store)
        self.assertEqual(admin.get('site_refill_policy','policy-test')['claim_window_days'],25)

    def test_guest_draft_gains_reuse_only_after_signin_without_overwriting_answers(self):
        other=self.prepare()
        guest=dict(self.patient,_reuse_allowed=False)
        form=self.service.initial_intake(other,guest)
        self.assertEqual(form['answers'],{})
        self.service.modify_initial(other,IntakePatch(revision=0,answers={'allergies':'An updated answer'}),guest)
        form=self.service.initial_intake(other,self.patient)
        self.assertEqual(form['answers'],{'height_inches':68,'allergies':'An updated answer'})
        self.assertEqual(form['revision'],2)
        self.assertEqual(self.service.initial_intake(other,self.patient)['revision'],2)
