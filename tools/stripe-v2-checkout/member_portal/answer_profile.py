"""Site/patient answer memory. Only submitted, granted intakes are reusable.

Question IDs are not semantic identity: adapters must supply a stable reuse_key,
version and policy. Verification assertions can only enter through the backend
adapter, never through patient answer PATCHes.
"""
from copy import deepcopy
import json
from fastapi import HTTPException
from patient_demo.app import clean_answers, visible


def annotate(template):
    """Conservative mappings for our versioned mock provider, including old forms."""
    template = deepcopy(template)
    if template.get('version') in ('mock-care-1', 'demo-1'):
        for q in template['questions']:
            if q['id'] in ('height_inches', 'current_medications', 'allergies', 'health_history'):
                q.setdefault('reuse_key', 'patient.' + q['id'])
                q.setdefault('reuse_version', '1')
                q.setdefault('reuse_policy', 'stable' if q['id'] == 'height_inches' else 'confirm')
    return template


class AnswerProfile:
    def __init__(self, service):
        self.s = service
        with service.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS member_verified_facts(
                site_id TEXT NOT NULL,patient_id TEXT NOT NULL,fact_key TEXT NOT NULL,
                version TEXT NOT NULL,status TEXT NOT NULL,provider TEXT NOT NULL,
                reference TEXT NOT NULL,verified_at REAL NOT NULL,expires_at REAL NOT NULL,
                PRIMARY KEY(site_id,patient_id,fact_key,version))''')

    def record_verification(self, *, site_id, patient_id, key, version, status,
                            provider, reference, verified_at, expires_at):
        """Trusted server adapter hook after authenticating the provider response.

        No HTTP patient route calls this. Store only status and an opaque provider
        reference, never ID images, ID numbers or SSNs.
        """
        if (key not in ('identity.id_verified', 'identity.ssn_verified')
                or status not in ('verified', 'revoked') or not version
                or not provider or not reference or len(reference) > 200
                or not 0 < verified_at <= self.s.clock() < expires_at):
            raise ValueError('Invalid verification assertion')
        with self.s.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM member_patients WHERE site_id=? AND id=?', (site_id, patient_id)).fetchone():
                raise ValueError('Patient does not belong to this site')
            previous = db.execute('SELECT verified_at FROM member_verified_facts WHERE site_id=? AND patient_id=? AND fact_key=? AND version=?', (site_id, patient_id, key, version)).fetchone()
            if previous and previous['verified_at'] > verified_at:
                raise ValueError('Stale verification assertion')
            db.execute('INSERT OR REPLACE INTO member_verified_facts VALUES(?,?,?,?,?,?,?,?,?)',
                       (site_id, patient_id, key, version, status, provider, reference, verified_at, expires_at))

    def seed(self, db, order, patient, template):
        template, answers = annotate(template), {}
        # A receipt may reuse its own trusted assertion without reading any
        # account answers. Account-wide facts still require authentication.
        for q in template['questions']:
            if q.get('reuse_policy') == 'verified':
                fact = self.s.identity_checks.fact(db, order, patient, q.get('reuse_key'), q.get('reuse_version', '1'))
                if fact:
                    try:
                        value = clean_answers(template, {q['id']: 'verified'})[q['id']]
                    except HTTPException:
                        continue
                    answers[q['id']] = value
                    q.update(saved_value=value, saved_at=fact['verified_at'], reuse_status='verified')
        if patient.get('_reuse_allowed') is False or not db.execute(
                'SELECT 1 FROM member_grants WHERE site_id=? AND order_id=? AND patient_id=?',
                (order['site_id'], order['order_id'], patient['id'])).fetchone():
            return template, answers
        # Existing submitted records are the durable profile. Read them only
        # through an exact site/patient/order grant; never search by email.
        records = list(db.execute('''SELECT i.template,i.submitted_answers,i.submitted,o.payload
            FROM member_intakes i JOIN member_grants g ON g.site_id=i.site_id AND g.order_id=i.order_id AND g.patient_id=i.patient_id
            JOIN member_orders o ON o.site_id=g.site_id AND o.order_id=g.order_id
            WHERE i.site_id=? AND i.patient_id=? AND i.status='submitted' ''', (order['site_id'], patient['id'])))
        for table in ('member_care_intakes', 'member_claim_intakes'):
            records += list(db.execute('''SELECT i.template,i.submitted_answers,i.submitted,o.payload
                FROM ''' + table + ''' i JOIN member_care_plans p ON p.id=i.plan_id
                JOIN member_grants g ON g.site_id=p.site_id AND g.order_id=p.term_order_id AND g.patient_id=p.patient_id
                JOIN member_orders o ON o.site_id=g.site_id AND o.order_id=g.order_id
                WHERE p.site_id=? AND p.patient_id=? AND i.status='submitted' AND i.simulated=0''', (order['site_id'], patient['id'])))
        facts = {}
        test = bool(json.loads(order['payload']).get('test_order'))
        for record in sorted(records, key=lambda r: r['submitted'] or 0):
            if bool(json.loads(record['payload']).get('test_order')) != test:
                continue
            old = annotate(json.loads(record['template']))
            values = json.loads(record['submitted_answers'] or '{}')
            for q in old['questions']:
                if q.get('reuse_key') and q.get('reuse_policy') in ('stable', 'confirm') and q['id'] in values and visible(q, values):
                    facts[(q['reuse_key'], q.get('reuse_version', '1'))] = (values[q['id']], record['submitted'])
        for q in template['questions']:
            policy, key, version = q.get('reuse_policy'), q.get('reuse_key'), q.get('reuse_version', '1')
            if not key or policy not in ('stable', 'confirm', 'verified'):
                continue
            if policy == 'verified':
                fact = db.execute('SELECT * FROM member_verified_facts WHERE site_id=? AND patient_id=? AND fact_key=? AND version=? AND status=? AND expires_at>?',
                    (order['site_id'], patient['id'], key, version, 'verified', self.s.clock())).fetchone()
                fact = fact or self.s.identity_checks.fact(db, order, patient, key, version)
                if not fact:
                    continue
                value, saved_at = 'verified', fact['verified_at']
            else:
                if (key, version) not in facts:
                    continue
                value, saved_at = facts[(key, version)]
                if q.get('reuse_max_age_days') is not None and self.s.clock() - saved_at > q['reuse_max_age_days'] * 86400:
                    continue
            try:
                value = clean_answers(template, {q['id']: value})[q['id']]
            except HTTPException:
                continue  # Type/options changed: ask again.
            if value in (None, '', []):
                continue
            q.update(saved_value=value, saved_at=saved_at, reuse_status=policy)
            if policy != 'confirm':
                answers[q['id']] = value
        if any(q.get('reuse_status') for q in template['questions']):
            template['_profile_seeded'] = True
        return template, answers

    def validate(self, db, order, patient, template, incoming=None, submit=False, answers=None):
        for q in template['questions']:
            if q.get('reuse_policy') != 'verified':
                continue
            if incoming is not None and q['id'] in incoming and incoming[q['id']] != (answers or {}).get(q['id']):
                raise HTTPException(422, 'Identity verification is supplied by the verification service')
            if submit and visible(q, answers or {}) and (q.get('required') or q['id'] in (answers or {})):
                valid = db.execute('SELECT 1 FROM member_verified_facts WHERE site_id=? AND patient_id=? AND fact_key=? AND version=? AND status=? AND expires_at>?',
                    (order['site_id'], patient['id'], q.get('reuse_key'), q.get('reuse_version', '1'), 'verified', self.s.clock())).fetchone()
                valid = valid or self.s.identity_checks.fact(db, order, patient, q.get('reuse_key'), q.get('reuse_version', '1'))
                if not valid or (answers or {}).get(q['id']) != 'verified':
                    raise HTTPException(409, 'Complete identity verification before submitting this intake')

    def hydrate(self, db, order, patient, record, table):
        """Adopt reusable values into a guest draft only after member authentication.

        Never overwrite an answer already typed, or rewrite a submitted form.
        """
        assert table in ('member_intakes', 'member_care_intakes', 'member_claim_intakes')
        record = dict(record)
        original = json.loads(record['template'])
        if record['status'] != 'draft' or original.get('_profile_seeded'):
            return record
        template, saved = self.seed(db, order, patient, original)
        if not any(q.get('reuse_status') for q in template['questions']):
            return record
        answers = json.loads(record['answers'])
        for q in template['questions']:
            if q['id'] in answers and q.get('reuse_policy') != 'verified':
                saved.pop(q['id'], None)
                for key in ('reuse_status', 'saved_value', 'saved_at'):
                    q.pop(key, None)
        template['_profile_seeded'] = True
        answers = saved | answers
        db.execute('UPDATE ' + table + ' SET template=?,answers=?,revision=revision+1 WHERE id=? AND revision=?',
                   (json.dumps(template), json.dumps(answers), record['id'], record['revision']))
        return dict(db.execute('SELECT * FROM ' + table + ' WHERE id=?', (record['id'],)).fetchone())


def reused_fields(template):
    return [q['id'] for q in template['questions'] if q.get('reuse_status') in ('stable', 'verified')]
