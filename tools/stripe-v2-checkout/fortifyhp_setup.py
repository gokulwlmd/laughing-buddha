"""Journaled, additive FortifyHP tenant setup in the shared Fly application.

Run `python -m fortifyhp_setup prepare`, review the safe summary, then explicitly
run `apply`. This creates catalog objects, never authorizations or orders. The
client's external system owns fulfillment of resulting Sticky orders.
"""
import copy
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

from admin import Brand
from catalog import quote, resolve
from external_fulfillment import FORTIFYHP_ACKNOWLEDGEMENT, fortifyhp_prepaid_supported
from fortifyhp_provisioning import WEBSITE_PRICES, fingerprint
from master import assignment_id, billing_terms, campaign_master_id, clone_product, model_rows, product_contract, product_contract_matches
from plans import ReadCache, choice_id, fingerprint as record_fingerprint
from prepaid import configuration, cycles_for, renewal_for
from sites import checkout_id
from therapy_skeletons import all_skeletons
from member_portal.site_setup import product_setup_for, bootstrap_site_care

ORIGIN = 'https://wlmd-stripe-test-0f89b1bb.fly.dev'
RUN_ID = 'fortifyhp-production-catalog-195-v1'
SITE = {'id': 'fortifyhp', 'name': 'FortifyHP', 'brand_id': 'fortifyhp', 'campaign_id': 195, 'revision': 1}
SOURCES = {
    'SEMA': {1: 45560, 3: 45561, 6: 45562, 12: 45563},
    'TIRZ': {1: 45564, 3: 45565, 6: 45566, 12: 45567},
    'SERM': {1: 17399, 3: 17952, 6: 33340, 12: 33341},
    'METFORM': {1: 33342, 3: 37839, 6: 33343, 12: 33344},
    'PT141': {1: 33364, 3: 33365, 6: 33366, 12: 33367},
}


def routing_fingerprint(campaign):
    return fingerprint({k: v for k, v in campaign.items() if k not in ('offers', 'updated_at', 'updator')})


class FortifySetup:
    def __init__(self, application):
        self.admin = application.state.admin
        self.api = self.admin.api
        if (self.admin.cfg.synthetic or self.admin.cfg.public_url != ORIGIN
                or self.admin.cfg.state_dir != Path('/data')):
            raise ValueError('Run only in the existing shared checkout app and its /data database')
        self.path = self.admin.cfg.state_dir / (RUN_ID + '.json')
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {'run_id': RUN_ID, 'operations': {}}
        # Other sites and their payment-test mappings are intentionally retained.
        # FortifyHP production masters live in campaign_master, not global master.

    def save(self):
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.state, sort_keys=True))
        os.chmod(temp, 0o600)
        temp.replace(self.path)

    def campaign(self):
        c = self.api.detail('/api/v2/campaigns/195')
        links = [r.get('provider', {}) for r in c.get('alternative_payments', []) if r.get('payment_method') == 'stripe_link']
        if (c.get('id') != 195 or c.get('is_active') != 1 or c.get('is_archived') not in (None, 0, False)
                or c.get('gateway_id') != 269 or len(links) != 1
                or int(links[0].get('id') or 0) != 269 or int(links[0].get('account_id') or 0) != 250):
            raise ValueError('FortifyHP campaign 195 / Stripe v2 profile 269 routing changed')
        g = self.api.detail('/api/v2/providers/payment/profiles/269')
        fields = g.get('fields', {}).get('account_fields', {})
        if (int(g.get('account_id') or 0) != 250 or g.get('currency', {}).get('code') != 'USD'
                or not str(fields.get('publishable_key', '')).startswith('pk_live_')
                or any(fields.get(k) not in (None, False, 0, '0', '') for k in ('capture_on_shipment', 'enable_delayed_capture'))):
            raise ValueError('FortifyHP USD immediate-capture gateway configuration changed')
        return c

    def prepare(self):
        for skeleton in all_skeletons():
            therapy = self.admin.get('therapy', skeleton['therapy']['id']) or {}
            if not therapy.get('enabled') or any(t not in therapy.get('treatments', []) for t in skeleton['therapy']['treatments']):
                raise ValueError('Shared therapy metadata needs review: ' + skeleton['therapy']['id'])
            for product in skeleton['products']:
                shared = self.admin.get('master', product['sku']) or {}
                if (not shared.get('enabled') or shared.get('therapy_id') != skeleton['therapy']['id']
                        or shared.get('treatment_id') != product['treatment_id']
                        or shared.get('product_duration_months') != product['duration_months']):
                    raise ValueError('Shared master metadata needs review: ' + product['sku'])
        campaign = self.campaign()
        ids = sorted({pid for terms in SOURCES.values() for pid in terms.values()})
        attached = {int(p['id']) for o in campaign.get('offers', []) for p in o.get('products', [])}
        if not set(ids).issubset(attached):
            raise ValueError('An approved physical source product is no longer in campaign 195')
        models = {int(m['id']): m for m in model_rows(self.api)}
        if any(mid not in models or int(models[mid].get('days') or 0) != days
               or (mid != 2 and int((models[mid].get('type') or {}).get('id') or 0) != 1)
               for mid, days in ((2, 0), (3, 30), (4, 90))):
            raise ValueError('The configured one-time / 30-day / 90-day billing models changed')
        with ThreadPoolExecutor(max_workers=6) as pool:
            sources = dict(zip(ids, pool.map(lambda pid: self.api.detail(f'/api/v2/products/{pid}'), ids)))
        rows = []
        for skeleton in all_skeletons():
            for product in skeleton['products']:
                sku = product['sku']; prefix = sku.split('-', 1)[0]; term = product['duration_months']
                source_id = SOURCES[prefix][term]; source = sources[source_id]
                expected_sku = {('SERM', 1): 'SERM-30-1B', ('SERM', 3): 'SERM-30-3B'}.get((prefix, term), f'{prefix}-{term}M')
                if (source.get('sku') != expected_sku or source.get('is_shippable') not in (1, '1', True)
                        or source.get('taxable', source.get('is_taxable')) not in (0, '0', False)):
                    raise ValueError('Physical source SKU/shipping/tax changed: ' + str(source_id))
                renewal = bool(product['renewal_months']); count = {6: 2, 12: 4}.get(term)
                total = Decimal(WEBSITE_PRICES[prefix][str(term)]); unit = total / (count or 1)
                if unit != unit.quantize(Decimal('.01')):
                    raise ValueError('Upfront price does not divide into exact cents: ' + sku)
                model = 4 if count else {1: 3, 3: 4}[term] if renewal else 2
                name = f"FortifyHP / {product['treatment']} / {term} months / " + ('Subscription' if renewal else 'One-time')
                # These clones copy physical product configuration. The master
                # SKU determines the requested treatment/term; no dose is inferred.
                body = clone_product(dict(source, sku=sku, description=name), name, sku, unit)
                config = configuration(count, renewal) if count else {}
                contract_offer = {**config, 'billing_models': [models[model]]}
                if count and not fortifyhp_prepaid_supported(campaign, body, contract_offer):
                    raise ValueError('Physical prepaid contract is not acknowledged: ' + sku)
                rows.append({'sku': sku, 'therapy_id': skeleton['therapy']['id'], 'treatment_id': product['treatment_id'],
                             'term_months': term, 'name': name, 'source_product_id': source_id,
                             'source_hash': fingerprint(source), 'source_contract': product_contract(dict(source, sku=sku)),
                             'total': format(total, '.2f'), 'unit': format(unit, '.2f'),
                             'model': model, 'billing_terms': billing_terms(models[model]),
                             'cycles': count, 'renewal': renewal, 'configuration': config, 'product_body': body})
        review = {'rows': rows, 'routing_hash': routing_fingerprint(campaign),
                  'original_offer_ids': [int(o['id']) for o in campaign.get('offers', [])],
                  'model_hashes': {str(mid): fingerprint(models[mid]) for mid in (2, 3, 4)},
                  'external_fulfillment_acknowledgement': FORTIFYHP_ACKNOWLEDGEMENT}
        previous = self.state.get('review')
        if previous:
            # Once new offers are attached, they are intentionally absent from
            # the preserved original offer list, not a new provisioning request.
            review['original_offer_ids'] = previous['original_offer_ids']
            if review != previous:
                raise ValueError('Prepared catalog/source/routing changed; reconcile instead of overwriting')
        else:
            if (any(s.get('id') == 'fortifyhp' or s.get('campaign_id') == 195 for s in self.admin.records('site'))
                    or any(a.get('campaign_id') == 195 for a in self.admin.records('assignment'))
                    or self.admin.get('brand', 'fortifyhp')):
                raise ValueError('Existing FortifyHP setup needs reconciliation before a fresh catalog run')
            self.state['review'] = review
            self.state['review_id'] = fingerprint(review)
            self.save()
        return {'review_id': self.state['review_id'], 'campaign_id': 195, 'gateway_id': 269,
                'products': len(rows), 'offers': len(rows), 'therapies': 4, 'purchase_options': 16,
                'original_offers_preserved': review['original_offer_ids'], 'remote_writes': 0}

    def write(self, key, method, path, body):
        allowed = ((method == 'POST' and path in ('/api/v2/products', '/api/v2/offers'))
                   or (method == 'PUT' and path == '/api/v2/campaigns/195' and set(body) == {'offers'}))
        if not allowed:
            raise ValueError('This setup cannot submit payment, order, or unrelated mutation APIs')
        digest = fingerprint(body); old = self.state['operations'].get(key)
        if old:
            if old.get('body_hash') != digest or old.get('status') != 'confirmed':
                raise ValueError('Reconcile recorded operation before retry: ' + key)
            return old['object_id']
        self.state['operations'][key] = {'method': method, 'path': path, 'body_hash': digest, 'status': 'pending'}
        self.save()
        response = self.api.call(method, path, body)
        if str(response.get('status', '')).upper() != 'SUCCESS':
            raise ValueError('Sticky did not confirm ' + key + '; reconcile before retry')
        oid = (response.get('data') or {}).get('id') or (response.get('data') or {}).get('c_id')
        if method == 'POST' and not oid:
            raise ValueError('Sticky omitted created ID; reconcile ' + key)
        self.state['operations'][key].update(status='confirmed', object_id=int(oid or 195))
        self.save()
        return int(oid or 195)

    def apply(self):
        self.prepare()
        if self.state.get('published'):
            return self.verify()
        with self.admin.store.db() as db:
            if db.execute("SELECT 1 FROM checkouts WHERE campaign=195 AND status NOT IN ('new','captured') LIMIT 1").fetchone():
                raise ValueError('Campaign 195 has an unfinished payment; preserve it before attaching new offers')
        review = self.state['review']
        current_ids = [int(o['id']) for o in self.campaign().get('offers', [])]
        confirmed_ids = [self.state['operations'].get('offer:' + r['sku'], {}).get('object_id')
                         for r in review['rows']]
        completed_ids = review['original_offer_ids'] + confirmed_ids if all(confirmed_ids) else None
        if current_ids != review['original_offer_ids'] and current_ids != completed_ids:
            raise ValueError('Campaign offers changed concurrently; no new catalog writes submitted')
        for row in review['rows']:
            pid = self.write('product:' + row['sku'], 'POST', '/api/v2/products', row['product_body'])
            p = self.api.detail(f'/api/v2/products/{pid}')
            if (p.get('sku') != row['sku'] or Decimal(str(p.get('price'))) != Decimal(row['unit'])
                    or not product_contract_matches(row['source_contract'], product_contract(p))):
                raise ValueError('New physical product read-back mismatch: ' + row['sku'])
            body = {'type_id': 1, 'recurring': {'cycle_type_id': 1, 'terminating_cycle_type_id': 2},
                    **row['configuration'], 'name': row['name'], 'is_trial': 0,
                    'products': [{'id': pid}], 'billing_models': [{'id': row['model']}]}
            oid = self.write('offer:' + row['sku'], 'POST', '/api/v2/offers', body)
            o = self.api.detail(f'/api/v2/offers/{oid}')
            if ({int(p['id']) for p in o.get('products', [])} != {pid}
                    or {int(m['id']) for m in o.get('offer_billing_models', o.get('billing_models', []))} != {row['model']}
                    or cycles_for(o) != row['cycles'] or renewal_for(o) != (row['renewal'] if row['cycles'] else False)):
                raise ValueError('New offer read-back mismatch: ' + row['sku'])
        c = self.campaign()
        if routing_fingerprint(c) != review['routing_hash']:
            raise ValueError('Campaign routing changed; no offer attachment submitted')
        new_ids = [self.state['operations']['offer:' + r['sku']]['object_id'] for r in review['rows']]
        current = [int(o['id']) for o in c.get('offers', [])]
        target = review['original_offer_ids'] + new_ids
        if current != review['original_offer_ids'] and current != target:
            raise ValueError('Campaign offers changed concurrently; do not replace them')
        self.write('attach:195', 'PUT', '/api/v2/campaigns/195', {'offers': target})
        c = self.campaign()
        if set(int(o['id']) for o in c.get('offers', [])) != set(target) or routing_fingerprint(c) != review['routing_hash']:
            raise ValueError('Campaign attachment/routing read-back needs reconciliation')
        verified = self.verify_quotes()
        self.publish_local(verified)
        return self.state['published']

    def verify_quotes(self):
        cache = ReadCache(self.api)
        selections = [f"{self.state['operations']['offer:' + r['sku']]['object_id']}:{self.state['operations']['product:' + r['sku']]['object_id']}:{r['model']}" for r in self.state['review']['rows']]
        cache.prefetch_choices(195, selections)
        checks = []
        for row, selection in zip(self.state['review']['rows'], selections):
            c = resolve(cache, 195, row['sku'], allowed_keys=[selection])
            q = quote(cache, c, selection, 2, {'country': 'US', 'region': 'CA', 'postal_code': '94105'})
            if q['currency'] != 'usd' or Decimal(q['total']) != Decimal(row['total']):
                raise ValueError('Full-term Sticky quote mismatch: ' + row['sku'])
            checks.append({'sku': row['sku'], 'selection': selection, 'total': row['total'], 'currency': 'USD'})
        return checks

    def publish_local(self, checks):
        if len(checks) != 40:
            raise ValueError('All forty full-term quotes must pass before publication')
        brand = Brand.model_validate({'id': 'fortifyhp', 'name': 'FortifyHP', 'campaign_id': 195,
                    'campaign_ids': [195], 'color': '#A2563F', 'background_color': '#F4F1EC',
                    'text_color': '#141312', 'support_email': 'support@fortifyhp.com'}).model_dump(mode='json')
        records = [('brand', 'fortifyhp', brand), ('site', 'fortifyhp', SITE)]
        by_sku = {r['sku']: r for r in self.state['review']['rows']}
        checked = {r['sku']: r for r in checks}
        for row in by_sku.values():
            sku = row['sku']; pid = self.state['operations']['product:' + sku]['object_id']
            oid = self.state['operations']['offer:' + sku]['object_id']; aid = assignment_id('fortifyhp', 195, sku)
            name = row['name'].removeprefix('FortifyHP / ')
            master_offer = {'id': 'upfront', 'name': 'Full-term upfront', 'price': row['total'], 'billing_models': [row['model']]}
            if row['cycles']:
                master_offer.update(prepaid_cycles=row['cycles'], prepaid_renewal=row['renewal'])
            master = {'sku': sku, 'name': name, 'category': row['therapy_id'], 'therapy_id': row['therapy_id'],
                      'treatment_id': row['treatment_id'], 'product_duration_months': row['term_months'],
                      'product_id': None, 'fulfillment_product_id': row['source_product_id'],
                      'product_template': dict(row['product_body'], price=0), 'currency': 'USD', 'enabled': True,
                      'offers': [master_offer], 'billing_terms': {str(row['model']): row['billing_terms']}, 'revision': 1,
                      'product_setup': product_setup_for(sku)}
            slot = {'id': 'master-' + aid + '-upfront', 'brand_id': 'fortifyhp', 'campaign_id': 195,
                    'sku': sku, 'name': 'Full-term upfront', 'price': row['total'], 'billing_models': [row['model']],
                    'configuration': row['configuration'], 'product_id': pid, 'offer_id': oid}
            assignment = {'id': aid, 'brand_id': 'fortifyhp', 'campaign_id': 195, 'sku': sku,
                          'master_revision': 1, 'currency': 'USD', 'name': name,
                          'offers': [slot | {'master_offer_id': 'upfront'}], 'link_id': 'master-' + aid,
                          'source_hash': record_fingerprint(master['product_template']), 'source_contract': row['source_contract'],
                          'billing_terms': master['billing_terms']}
            overlay_id = campaign_master_id('fortifyhp', 195, sku)
            overlay = {'id': overlay_id, 'brand_id': 'fortifyhp', 'campaign_id': 195, 'sku': sku, 'master': master}
            records.extend([('campaign_master', overlay_id, overlay),
                            ('offering', slot['id'], slot), ('assignment', aid, assignment)])
            records.append(('link', assignment['link_id'], {'id': assignment['link_id'], 'brand_id': 'fortifyhp',
                            'campaign_id': 195, 'sku': sku, 'title': name, 'visibility': 'private',
                            'enabled': True, 'options': [checked[sku]['selection']], 'revision': 1}))
        pending = {(k, i): v for k, i, v in records}
        view = copy.copy(self.admin)
        view.get = lambda kind, key: pending.get((kind, key), self.admin.get(kind, key))
        plan_ids = []
        for skeleton in all_skeletons():
            therapy = self.admin.get('therapy', skeleton['therapy']['id'])
            pending['therapy', therapy['id']] = therapy
            template_id = 'fortifyhp-' + therapy['id']
            purchases = []
            for term in (1, 3, 6, 12):
                purchase = {'id': f'{template_id}-{term}m', 'name': f'{term}-month plan', 'therapy_id': therapy['id'],
                            'duration_months': term, 'skus': [p['sku'] for p in skeleton['products'] if p['duration_months'] == term],
                            'payment_types': ['once', 'subscription'] if term <= 3 else ['prepaid'], 'enabled': True, 'revision': 1}
                records.append(('purchase_option', purchase['id'], purchase)); pending['purchase_option', purchase['id']] = purchase
                purchases.append(purchase)
            template = {'id': template_id, 'name': therapy['name'], 'title': 'Choose your ' + therapy['name'].lower() + ' plan',
                        'therapy_id': therapy['id'], 'purchase_option_ids': [p['id'] for p in purchases],
                        'site_id': 'fortifyhp', 'enabled': True, 'revision': 1}
            records.append(('checkout_template', template_id, template))
            source = view.template_source(template, SITE)
            plan_id = checkout_id('fortifyhp', template_id); plan_ids.append(plan_id)
            entries = [{'purchase_option_id': p['id'], 'sku': sku, 'options': [checked[sku]['selection']]}
                       for p in purchases for sku in p['skus']]
            plan = {'id': plan_id, 'brand_id': 'fortifyhp', 'campaign_id': 195, 'therapy_id': therapy['id'],
                    'title': template['title'], 'visibility': 'private', 'enabled': True, 'revision': 1,
                    'purchase_option_ids': template['purchase_option_ids'], 'purchase_options': purchases, 'entries': entries,
                    'site_id': 'fortifyhp', 'template_id': template_id, 'template_snapshot': source,
                    'template_source_hash': record_fingerprint(source), 'site_override': None, 'payment_test_only': False}
            records.append(('plan_checkout', plan_id, plan))
            for entry in entries:
                child_id = choice_id(plan_id, entry['sku'], entry['purchase_option_id'])
                records.append(('link', child_id, {'id': child_id, 'brand_id': 'fortifyhp', 'campaign_id': 195,
                                'sku': entry['sku'], 'title': by_sku[entry['sku']]['name'], 'visibility': 'private',
                                'enabled': True, 'options': entry['options'], 'revision': 1, 'plan_checkout_id': plan_id,
                                'purchase_option_id': entry['purchase_option_id'], 'payment_test_only': False}))
        with self.admin.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            for kind, key, value in records:
                existing = db.execute('SELECT data FROM admin_config WHERE kind=? AND id=?', (kind, key)).fetchone()
                if existing and json.loads(existing[0]) != value:
                    raise ValueError('Existing client configuration differs; no overwrite: ' + kind + ' ' + key)
            for kind, key, value in records:
                db.execute('INSERT OR IGNORE INTO admin_config(kind,id,data) VALUES(?,?,?)', (kind, key, json.dumps(value)))
        bootstrap_site_care(self.admin, 'fortifyhp')
        self.state['published'] = {'site_id': 'fortifyhp', 'campaign_id': 195, 'gateway_id': 269,
                                   'source_plan_ids': plan_ids, 'products': 40, 'offers': 40, 'quote_checks': len(checks),
                                   'payment_authorizations': 0, 'orders_created': 0, 'patient_records_copied': 0}
        self.save()

    def verify(self):
        self.prepare()
        checks = self.verify_quotes()
        if not self.state.get('published'):
            raise ValueError('Catalog exists but local publication is not complete')
        bootstrap_site_care(self.admin, 'fortifyhp')
        return dict(self.state['published'], quote_checks=len(checks))


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'apply', 'verify'))
    args = parser.parse_args()
    from app import app
    result = getattr(FortifySetup(app), args.action)()
    print(json.dumps(result))


if __name__ == '__main__':
    main()
