"""Explicitly acknowledged external Sticky-order fulfillment capabilities.

FortifyHP's operator confirmed that its external system consumes Sticky orders
and performs fulfillment. This capability does not mark an order prescribed,
shipped, or clinically approved, and does not place any refill order itself.
"""
import re
from decimal import Decimal, InvalidOperation

from prepaid import cycles_for, renewal_for

FORTIFYHP_ACKNOWLEDGEMENT = 'fortifyhp-external-sticky-order-fulfillment-2026-10-23'
FORTIFYHP_PREPAID_SKU = re.compile(r'(SEMA|TIRZ|SERM|METFORM|PT141)-(6|12)M(-SUB)?')


# Owner requested this exact new plan on FortifyHP, 26 October 2026.
# Other wellness master drafts are not implicitly enabled for fulfillment.
def fortifyhp_prepaid_terms(sku):
    if sku == 'NAD-INJ-12M-SUB':
        return 4, True
    match = FORTIFYHP_PREPAID_SKU.fullmatch(str(sku))
    return ({6: 2, 12: 4}[int(match[2])], bool(match[3])) if match else None


def fortifyhp_order_scope(campaign_id, gateway_id, sku):
    """Lightweight display scope; never sufficient authorization for a write."""
    try:
        return (int(campaign_id) == 195 and int(gateway_id) == 269
                and fortifyhp_prepaid_terms(sku) is not None)
    except (TypeError, ValueError):
        return False


def fortifyhp_prepaid_supported(campaign, product, offer):
    """Accept only the agreed non-taxable, quarterly FortifyHP prepaid contract.

    Ordinary catalog, gateway, quote, exact-price and order read-back checks are
    still required by callers. Other campaigns, models, taxes, currencies and
    product families retain the existing unverified-fulfillment restriction.
    """
    try:
        if int(campaign.get('id') or campaign.get('c_id') or 0) != 195:
            return False
        routes = [r.get('provider', {}) for r in campaign.get('alternative_payments', [])
                  if r.get('payment_method') == 'stripe_link']
        if (int(campaign.get('gateway_id') or 0) != 269 or len(routes) != 1
                or int(routes[0].get('id') or 0) != 269
                or int(routes[0].get('account_id') or 0) != 250):
            return False
        if not any(int(p.get('id') or 0) == 2 for p in campaign.get('shipping_profiles', [])):
            return False
        if not any(p.get('iso_2') == 'US' for p in campaign.get('countries', [])):
            return False
        terms = fortifyhp_prepaid_terms(product.get('sku', ''))
        if not terms or product.get('is_shippable') not in (True, 1, '1'):
            return False
        if product.get('taxable', product.get('is_taxable')) not in (False, 0, '0'):
            return False
        cycles, renewal = terms
        if cycles_for(offer) != cycles or renewal_for(offer) != renewal:
            return False
        models = offer.get('offer_billing_models') or offer.get('billing_models', [])
        if len(models) != 1:
            return False
        model = models[0]
        return (int(model.get('id') or 0) == 4 and int(model.get('days') or 0) == 90
                and int((model.get('type') or {}).get('id') or 0) == 1
                and Decimal(str(model.get('discount') or 0)) == 0)
    except (ValueError, TypeError, InvalidOperation, KeyError):
        return False
