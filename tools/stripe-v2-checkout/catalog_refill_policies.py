"""Exact approved catalog bindings; no SKU parsing or cross-therapy defaults."""
import json
from pathlib import Path
from functools import lru_cache


@lru_cache(maxsize=1)
def source_products():
    return json.loads(Path(__file__).with_name('wellness_master_catalog.json').read_text())['products']


@lru_cache(maxsize=1)
def additional_source_products():
    return json.loads(Path(__file__).with_name('additional_master_catalog.json').read_text())['products']


@lru_cache(maxsize=1)
def next_source_products():
    return json.loads(Path(__file__).with_name('next_master_catalog.json').read_text())['products']


@lru_cache(maxsize=1)
def ed_combination_source_products():
    return json.loads(Path(__file__).with_name('ed_combination_catalog.json').read_text())['products']


@lru_cache(maxsize=1)
def ed_advanced_source_products():
    return json.loads(Path(__file__).with_name('ed_advanced_catalog.json').read_text())['products']


@lru_cache(maxsize=1)
def ed_sublingual_source_products():
    return json.loads(Path(__file__).with_name('ed_sublingual_catalog.json').read_text())['products']


@lru_cache(maxsize=1)
def skin_topical_source_products():
    return json.loads(Path(__file__).with_name('skin_topical_catalog.json').read_text())['products']


@lru_cache(maxsize=1)
def dhea_source_products():
    return json.loads(Path(__file__).with_name('dhea_master_catalog.json').read_text())['products']


@lru_cache(maxsize=1)
def dhea_preg_source_products():
    return json.loads(Path(__file__).with_name('dhea_preg_catalog.json').read_text())['products']


@lru_cache(maxsize=1)
def remaining_source_products():
    return json.loads(Path(__file__).with_name('remaining_master_catalog.json').read_text())['products']


def astv_source_products():
    """Finalized exact 5-pack sheet row only; longer Sticky terms are deferred."""
    return [dict(sku=f'ASTV-5P-{months}M', therapy_id='erectile-dysfunction',
        treatment_id='astv-5pack', name='4-in-1 ED blend · 5-pack',
        duration_months=months, supply_days_per_shipment=30,
        shipments_per_term=1, included_refills=0,
        packets_per_shipment=5, total_packets=5, check_in_required=False)
        for months in (1,)]


def source_binding(sku):
    for p in source_products() + additional_source_products() + next_source_products() + astv_source_products() + ed_combination_source_products() + ed_advanced_source_products() + ed_sublingual_source_products() + skin_topical_source_products() + dhea_source_products() + dhea_preg_source_products() + remaining_source_products():
        if sku in (p['sku'], p['sku'] + '-SUB'):
            return {'template_id': p['therapy_id'], 'product_name': p['name'],
                    'duration_months': p['duration_months'], 'check_in_required': p['check_in_required']}
    from external_fulfillment import rollout_product
    p = rollout_product(sku)
    if p:
        return {'template_id': p['therapy_id'], 'product_name': p['medication'],
                'duration_months': p['duration_months'], 'check_in_required': p['check_in_required']}
    return None


def proposed_policy(product, sku):
    from refill_rules import RefillRules
    count, interval = product['shipments_per_term'], product['supply_days_per_shipment']
    return dict(RefillRules().model_dump(), sku=sku, revision=1, enabled=True,
        initial_intake_required=True, intake_template_id=product['therapy_id'],
        included_refills_enabled=count > 1, claim_window_days=20,
        check_in_required=product['check_in_required'],
        check_in_days=[i * interval for i in range(1, count)] if product['check_in_required'] else [],
        allow_paid_early_renewal=sku.endswith('-SUB') and count == 1)
