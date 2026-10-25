"""Exact approved catalog bindings; no SKU parsing or cross-therapy defaults."""
import json
from pathlib import Path
from functools import lru_cache


@lru_cache(maxsize=1)
def source_products():
    return json.loads(Path(__file__).with_name('wellness_master_catalog.json').read_text())['products']


def source_binding(sku):
    for p in source_products():
        if sku in (p['sku'], p['sku'] + '-SUB'):
            return {'template_id': p['therapy_id'], 'product_name': p['name'],
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
