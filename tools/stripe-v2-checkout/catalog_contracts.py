"""Owner-defined purchase contracts for new paired master-therapy drafts."""


def validate_purchase_pairs(masters, base_skus):
    """Reject missing/mislabelled purchase types before importing a recipe.

    Scope this to newly built paired recipes, not unrelated legacy Sticky SKUs.
    Price may differ by purchase type; product identity and deliveries may not.
    """
    bases = set(base_skus)
    rows = {m['sku']: m for m in masters}
    if (any(s.endswith('-SUB') for s in bases) or len(rows) != len(masters)
            or set(rows) != bases | {s + '-SUB' for s in bases}):
        raise ValueError('Every base SKU must have exactly one -SUB counterpart')
    for sku in bases:
        once, sub = rows[sku], rows[sku + '-SUB']
        a, b = once.get('planning_contract') or {}, sub.get('planning_contract') or {}
        term = once.get('product_duration_months')
        if (not term or a.get('term_months') != term or b.get('term_months') != term
                or a.get('charge') != 'full_term_upfront' or b.get('charge') != 'full_term_upfront'
                or a.get('renewal_months') is not None or b.get('renewal_months') != term):
            raise ValueError(sku + ': base must be one-time; -SUB must renew the full upfront term')
        for field in ('therapy_id', 'treatment_id', 'product_duration_months', 'currency'):
            if once.get(field) != sub.get(field):
                raise ValueError(sku + ': paired product identity differs')
        for field in ('shipments_per_term', 'shipment_interval', 'later_shipment_charge'):
            if a.get(field) != b.get(field):
                raise ValueError(sku + ': paired shipment schedules differ')
        if a.get('later_shipment_charge') != '0.00':
            raise ValueError(sku + ': included intermediate shipments must be $0')
