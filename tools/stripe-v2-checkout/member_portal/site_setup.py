"""Idempotent, site-bound care metadata for the approved FortifyHP catalog.

Only admin configuration is written. Shared masters, patient records, Sticky
orders and existing brands are never changed by this bootstrap.
"""
from copy import deepcopy
import json

from plans import fingerprint
from refill_rules import RefillRules, site_rule_key
from therapy_skeletons import all_skeletons

PRODUCTS = {product['sku']: dict(product, therapy_id=skeleton['therapy']['id'])
            for skeleton in all_skeletons() for product in skeleton['products']}


def product_setup_for(sku):
    product = PRODUCTS[sku]
    term = product['duration_months']
    count = product['shipments_per_term'] or 1
    interval = product['shipment_interval'] or term * 30
    return {'payment_setup': 'prepaid' if count > 1 else 'upfront',
            'term_months': term, 'renewal_months': product['renewal_months'],
            'renewal_days': product['renewal_days'], 'prepaid_cycles': count if count > 1 else None,
            'shipment_count': count, 'shipment_interval_days': interval,
            'shipment_days': [index * interval for index in range(count)],
            'later_shipment_charge': '0.00'}


def refill_policy_for(sku, site_id):
    product, setup = PRODUCTS[sku], product_setup_for(sku)
    days = setup['shipment_days'][1:]
    rule = RefillRules(enabled=True, intake_template_id=product['therapy_id'],
                       initial_intake_required=True, check_in_required=True,
                       check_in_days=days, included_refills_enabled=bool(days),
                       claim_window_days=10).model_dump()
    return dict(rule, site_id=site_id, sku=sku, revision=1)


def bootstrap_site_care(admin, site_id='fortifyhp'):
    """Fill only missing approved care metadata; never overwrite owner edits."""
    site = admin.get('site', site_id) or {}
    if site.get('brand_id') != 'fortifyhp' or site.get('campaign_id') != 195:
        raise ValueError('Select the verified FortifyHP site in campaign 195')
    changed_plans, created_policies, found = [], [], set()
    with admin.store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        records = {(kind, key): json.loads(data) for kind, key, data in db.execute(
            "SELECT kind,id,data FROM admin_config WHERE kind IN ('plan_checkout','site_refill_policy')")}
        for (kind, key), saved in records.items():
            if kind != 'plan_checkout' or saved.get('site_id') != site_id:
                continue
            if saved.get('brand_id') != site['brand_id'] or saved.get('campaign_id') != 195:
                raise ValueError('Site checkout ownership changed; no care metadata written')
            plan = deepcopy(saved)
            snapshot = plan.get('template_snapshot') or {}
            masters = snapshot.get('masters') or []
            if not masters:
                raise ValueError('A site checkout is missing its purchased-product snapshot')
            for master in masters:
                sku = master.get('sku')
                if sku not in PRODUCTS:
                    raise ValueError('A site checkout contains an unapproved treatment SKU')
                found.add(sku)
                setup = product_setup_for(sku)
                old = master.get('product_setup') or {}
                if any(field in old and old[field] != value for field, value in setup.items()):
                    raise ValueError('Existing site product schedule differs; preserve it for review: ' + sku)
                master['product_setup'] = dict(old, **setup)
            if snapshot != saved.get('template_snapshot'):
                plan['template_snapshot'] = snapshot
                plan['template_source_hash'] = fingerprint(snapshot)
                changed_plans.append((key, plan))
        if found != set(PRODUCTS):
            raise ValueError('All four approved therapies must be mapped before care bootstrap')
        for sku in sorted(found):
            key = site_rule_key(site_id, sku)
            existing = records.get(('site_refill_policy', key))
            if existing:
                if existing.get('site_id') != site_id or existing.get('sku') != sku:
                    raise ValueError('Site refill policy ownership changed')
                # A later owner edit is authoritative, including disabling claims.
                continue
            created_policies.append((key, refill_policy_for(sku, site_id)))
        for key, plan in changed_plans:
            db.execute("UPDATE admin_config SET data=? WHERE kind='plan_checkout' AND id=?", (json.dumps(plan), key))
        for key, rule in created_policies:
            db.execute("INSERT INTO admin_config(kind,id,data) VALUES('site_refill_policy',?,?)", (key, json.dumps(rule)))
    return {'site_id': site_id, 'configured_skus': len(found),
            'updated_plans': len(changed_plans), 'created_policies': len(created_policies),
            'patient_records_written': 0, 'provider_writes': 0}
