"""Versioned CoreAge presentation repair and exact-order contact defaults.

No clinical approval, provider submission or account-wide lookup happens here.
Submitted questionnaires retain their original version and answers.
"""
from copy import deepcopy
import json
from pathlib import Path

REVISION = 'coreage-steps-2026-10-26-v2'
CONTACT = {'ca_199': 'name', 'ca_200': 'email', 'ca_202': 'phone',
           'ca_571': 'address', 'ca_196': 'region'}


def upgrade(template):
    if not str(template.get('version', '')).startswith(('coreage-reference-', 'coreage-steps-')):
        return deepcopy(template)
    current = json.loads((Path(__file__).parent / 'weight_loss_questions.json').read_text())
    old = {q['id']: q for q in template['questions']}
    result = deepcopy(template)
    result.update(version=REVISION, sections=current['sections'])
    result['questions'] = [dict(q, **{k: v for k, v in old.get(q['id'], {}).items()
        if k in ('reuse_status', 'saved_value', 'saved_at', 'prefill_source')}) for q in current['questions']]
    return result


def contact_defaults(service, order, template):
    if not str(template.get('version', '')).startswith('coreage-'):
        return {}
    raw = json.loads(order['payload']); customer = raw.get('customer') or {}; address = raw.get('shipping_address') or {}
    values = {'name': customer.get('name'), 'email': customer.get('email'), 'phone': customer.get('phone'),
              'region': address.get('region'), 'address': ', '.join(str(address[k]) for k in
              ('address','address2','city','region','postal_code','country') if address.get(k))}
    # Recover phone from only this site's verified captured receipt. Never search
    # by email or disclose another order's contact/profile through a receipt.
    for receipt in service.captured(order['site_id'], order['order_id']):
        contact = json.loads(receipt.get('contact') or '{}')
        for key in ('name','email','phone','region'):
            if not values.get(key): values[key] = contact.get(key)
        if not values['address']:
            values['address'] = ', '.join(str(contact[k]) for k in ('address','city','region','postal_code','country') if contact.get(k))
        break
    defaults = {}
    for q in template['questions']:
        value = values.get(CONTACT.get(q['id']))
        if not value: continue
        if q['id'] == 'ca_196':
            value = next((o['value'] for o in q.get('options', []) if str(value).casefold() in
                (o['value'].casefold(), o['value'].rsplit(' (',1)[0].casefold(), o['value'][-3:-1].casefold())), None)
        if value: defaults[q['id']] = str(value)[:1000]
    return defaults


def prepare_record(service, db, order, record, table):
    record = dict(record)
    if record['status'] != 'draft': return record
    old = json.loads(record['template'])
    if not str(old.get('version', '')).startswith('coreage-'): return record
    template = upgrade(old); answers = json.loads(record['answers'])
    old_section = old['sections'][min(record['current_step'], len(old['sections'])-1)]['id']
    step = record['current_step']
    if old.get('version') != template.get('version'):
        anchor = next((q['id'] for q in old['questions'] if q['section_id'] == old_section), None)
        section = next((q['section_id'] for q in template['questions'] if q['id'] == anchor), template['sections'][0]['id'])
        step = next(i for i,s in enumerate(template['sections']) if s['id'] == section)
    if not template.get('_checkout_prefilled'):
        defaults = contact_defaults(service, order, template)
        for q in template['questions']:
            value = defaults.get(q['id'])
            if value and q['id'] not in answers:
                answers[q['id']] = value
                q.update(reuse_status='stable', prefill_source='checkout', saved_value=value)
        template['_checkout_prefilled'] = True
    if template != old or answers != json.loads(record['answers']) or step != record['current_step']:
        db.execute('UPDATE '+table+' SET template=?,answers=?,current_step=?,revision=revision+1 WHERE id=? AND revision=?',
                   (json.dumps(template), json.dumps(answers), step, record['id'], record['revision']))
        record = dict(db.execute('SELECT * FROM '+table+' WHERE id=?', (record['id'],)).fetchone())
    return record
