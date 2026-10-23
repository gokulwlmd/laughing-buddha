"""Read-only FortifyHP production catalog planner.

Consumes sanitized inspection snapshots. It has no credentials, network client,
database access, or apply function. In particular, payment-test activations are
not production mappings. Existing campaign products/offers are never reused by
SKU alone and never edited by this plan.
"""
import argparse
import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from therapy_skeletons import all_skeletons
from external_fulfillment import FORTIFYHP_ACKNOWLEDGEMENT

SITE_ID = 'fortifyhp'
CAMPAIGN_ID = 195
GATEWAY_ID = 269
PRICE_SOURCE = {
    'kind': 'website_source_fallback',
    'commit': '172e30434dffb2efb8d5b209e01be13f1b377f4a',
    'status': 'proposed_default_not_verified_live_feed',
}
# Full-term USD amounts read from this client's Lovable source. These are not
# monthly prices and do not establish the live pharmacy feed's current amounts.
WEBSITE_PRICES = {
    'SEMA': {'1': '199.00', '3': '537.30', '6': '1014.90', '12': '1428.00'},
    'TIRZ': {'1': '299.00', '3': '807.30', '6': '1524.90', '12': '2268.00'},
    'SERM': {'1': '189.00', '3': '510.30', '6': '963.90', '12': '1814.40'},
    'METFORM': {'1': '69.00', '3': '75.00', '6': '150.00', '12': '300.00'},
    'PT141': {'1': '199.00', '3': '537.30', '6': '1014.90', '12': '1910.40'},
}
PRODUCTION_REQUIREMENTS = [
    'site_scoped_production_mapping_without_payment_test_activation',
    'verified_physical_product_and_fulfillment_contract',
    'preserve_external_sticky_order_consumer_fulfillment_responsibility',
    'new_product_offer_and_quote_readback',
    'public_site_api_and_patient_account_handoff',
]
PREPAID_REQUIREMENTS = [
    'fortifyhp_scoped_shippable_prepaid_contract_and_quote_readback',
    'included_refill_claim_without_duplicate_scheduled_shipment',
    'checkin_link_for_each_included_shipment',
    'zero_dollar_child_order_and_full_term_renewal_verification',
]


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def money(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal('.01')):
            raise ValueError()
    except (InvalidOperation, ValueError):
        raise ValueError('Supply a positive full-term price in exact cents') from None
    return format(amount, '.2f')


def check_gateway(snapshot):
    campaign = snapshot['campaign']
    if (campaign.get('id') != CAMPAIGN_ID or campaign.get('is_active') != 1
            or campaign.get('is_archived') not in (None, 0, False)
            or campaign.get('gateway_id') != GATEWAY_ID):
        raise ValueError('Recheck FortifyHP campaign 195 and gateway 269 before planning')
    routes = [r for r in snapshot.get('routes', []) if r.get('method') == 'stripe_link']
    if routes != [{'method': 'stripe_link', 'profile_id': GATEWAY_ID, 'provider_id': 250}]:
        raise ValueError('FortifyHP Stripe Link routing changed')
    gateways = [g for g in snapshot.get('gateways', []) if g.get('id') == GATEWAY_ID]
    if len(gateways) != 1:
        raise ValueError('FortifyHP gateway read-back is missing')
    gateway = gateways[0]
    if (gateway.get('account_id') != 250 or gateway.get('currency') != 'USD'
            or gateway.get('publishable_key_mode') != 'live'
            or gateway.get('capture_on_shipment') not in (False, 0, '0')
            or gateway.get('enable_delayed_capture') not in (False, 0, '0')):
        raise ValueError('FortifyHP immediate-capture USD gateway needs review')


def build_manifest(campaign, catalog, admin, prices=None, brand_price_overrides=None):
    """Return a deterministic review, preserving saved brand prices if supplied.

    Source product IDs remain candidates, never an implicit dose/fulfillment
    decision. Standard plans may be implemented first, but neither stage is
    marked payable by this planner. A separate reviewed executor must use the
    existing journal/read-back workflow and stop on uncertain writes.
    """
    check_gateway(campaign)
    if catalog.get('catalog', {}).get('campaign_id') != CAMPAIGN_ID:
        raise ValueError('Product evidence must belong to campaign 195')
    for site in admin.get('site_summaries', []):
        if site.get('id') == SITE_ID or site.get('campaign_id') == CAMPAIGN_ID:
            raise ValueError('An existing site needs explicit reconciliation; do not overwrite it')
    if admin.get('fortify_brand') or admin.get('campaign195_assignments'):
        raise ValueError('Existing FortifyHP assignments need read-back before another provisioning plan')
    prices = prices if prices is not None else WEBSITE_PRICES
    overrides = brand_price_overrides or {}
    products, plans, templates = [], [], []
    candidates = catalog['catalog'].get('exact_master_sku_matches', [])
    master_evidence = {m['sku']: m for m in admin.get('masters', [])}
    for skeleton in all_skeletons():
        therapy = skeleton['therapy']
        template_id = f'fortifyhp-{therapy["id"]}'
        plan_ids = []
        for term in (1, 3, 6, 12):
            plan_id = f'{template_id}-{term}m'
            plan_ids.append(plan_id)
            skus = [p['sku'] for p in skeleton['products'] if p['duration_months'] == term]
            plans.append({'id': plan_id, 'therapy_id': therapy['id'], 'duration_months': term,
                          'skus': skus, 'payment_types': ['once', 'subscription'] if term <= 3 else ['prepaid'],
                          'enabled': False, 'stage': 'standard' if term <= 3 else 'prepaid_pending_readback'})
        templates.append({'id': template_id, 'therapy_id': therapy['id'],
                          'purchase_option_ids': plan_ids, 'enabled': False,
                          'routes': [f'/{gender}/products/{therapy["id"]}' for gender in ('men', 'women')]})
        for product in skeleton['products']:
            sku = product['sku']
            if sku not in master_evidence:
                raise ValueError('Master metadata is missing for ' + sku)
            saved = master_evidence[sku]
            if (saved.get('therapy_id') != therapy['id']
                    or saved.get('treatment_id') != product['treatment_id']
                    or saved.get('duration_months') != product['duration_months']):
                raise ValueError('Master therapy/duration changed for ' + sku)
            term = product['duration_months']
            renewable = bool(product['renewal_months'])
            prefix = sku.split('-', 1)[0]
            total = money(overrides[sku] if sku in overrides else prices[prefix][str(term)])
            shipments = {1: 1, 3: 1, 6: 2, 12: 4}[term]
            unit = Decimal(total) / shipments
            if unit != unit.quantize(Decimal('.01')):
                raise ValueError('Prepaid total does not divide into exact-cent shipment units: ' + sku)
            prepaid = shipments > 1
            base_sku = sku.removesuffix('-SUB')
            sources = [{k: p.get(k) for k in ('id', 'offer_id', 'sku', 'is_shippable', 'taxable')}
                       for p in candidates if p.get('sku') == base_sku and p.get('archived_flag') == 0]
            requirements = PRODUCTION_REQUIREMENTS + (PREPAID_REQUIREMENTS if prepaid else [])
            if len(sources) != 1:
                requirements = requirements + ['explicit_source_product_selection']
            billing_days = 90 if prepaid else term * 30 if renewable else 0
            products.append({
                'sku': sku, 'therapy_id': therapy['id'], 'treatment_id': product['treatment_id'],
                'duration_months': term, 'mapping_key': f'fortifyhp:195:{sku}',
                'action': 'create_independent_product_and_offer',
                'source_product_candidates': sources, 'source_product_selected': None,
                'is_shippable': True, 'currency': 'USD', 'full_term_price': total,
                'price_source': 'preserved_site_price' if sku in overrides else PRICE_SOURCE['kind'],
                'one_time': not renewable, 'renewal_days': term * 30 if renewable else None,
                'shipments_per_term': shipments, 'shipment_days': [90 * i for i in range(shipments)],
                'included_refill_claim_days': [90 * i - 10 for i in range(1, shipments)],
                'later_shipment_charge': '0.00', 'initial_intake_required': True,
                'checkin_count': shipments - 1,
                'offer': {'type_id': 2 if prepaid else 1,
                          'billing_model_id': {0: 2, 30: 3, 90: 4}[billing_days],
                          'billing_model_days': billing_days,
                          'prepaid_cycles': shipments if prepaid else None,
                          'prepaid_renewal': renewable if prepaid else False,
                          'product_unit_price': format(unit, '.2f')},
                'stage': 'prepaid_pending_readback' if prepaid else 'standard',
                'publishable': False, 'requirements': requirements,
                'test_activation_reused': False,
            })
    unknown_overrides = set(overrides) - {p['sku'] for p in products}
    if unknown_overrides:
        raise ValueError('Price overrides contain unknown FortifyHP SKUs')
    result = {
        'schema_version': 1, 'status': 'review_only', 'remote_writes': 0,
        'site': {'id': SITE_ID, 'name': 'FortifyHP', 'brand_id': SITE_ID, 'campaign_id': CAMPAIGN_ID},
        'gateway': {'profile_id': GATEWAY_ID, 'provider_id': 250, 'currency': 'USD', 'mode': 'live'},
        'fulfillment': {'owner': 'external_sticky_order_consumer',
                        'acknowledgement': FORTIFYHP_ACKNOWLEDGEMENT,
                        'local_pharmacy_integration_required': False,
                        'clinical_approval_inferred': False},
        'price_source': dict(PRICE_SOURCE),
        'existing_offer_ids_to_preserve': [o['id'] for o in campaign.get('offers', [])],
        'campaign_update_policy': 'append_only_after_fresh_campaign_fingerprint_and_readback',
        'existing_product_price_policy': 'never_modify',
        'existing_subscription_policy': 'never_modify',
        'shared_master_policy': 'preserve_shared_records_and_test_activations; use_site_scoped_production_mappings',
        'operation_policy': 'journal_intent_before_write; stop_on_pending_or_uncertain; reuse_confirmed_ids_after_readback',
        'templates': templates, 'purchase_options': plans, 'products': products,
        'counts': {'therapies': len(templates), 'purchase_options': len(plans),
                   'independent_products': len(products), 'independent_offers': len(products),
                   'standard_choices': sum(p['stage'] == 'standard' for p in products),
                   'prepaid_choices_pending_readback': sum(p['stage'] == 'prepaid_pending_readback' for p in products),
                   'payable_choices': 0},
    }
    result['review_id'] = 'fortifyhp-' + fingerprint(result)[:24]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', required=True, type=Path)
    parser.add_argument('--catalog', required=True, type=Path)
    parser.add_argument('--admin', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    manifest = build_manifest(*(json.loads(p.read_text()) for p in (args.campaign, args.catalog, args.admin)))
    args.output.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'review_id': manifest['review_id'], **manifest['counts'], 'remote_writes': 0}))


if __name__ == '__main__':
    main()
