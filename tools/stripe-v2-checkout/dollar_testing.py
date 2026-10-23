"""Owner-enabled $1 testing for explicitly non-fulfilling campaign 422 links.

Sticky calculates the override; preserve_price keeps renewals at the same unit
price. Verified on Dry Run campaign 428, orders 507822–507829 (2026-10-23).
Regular catalog prices and existing orders are never edited.
"""
import copy
from decimal import Decimal
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict
from catalog import CatalogError


class TestingSetting(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool


def site_id_for_link(admin, link_id):
    link = admin.get('link', link_id) if link_id else None
    parent = admin.get('plan_checkout', link.get('plan_checkout_id', '')) if link else None
    return parent.get('site_id') if parent else None


def available(admin, req, catalog):
    site_id = site_id_for_link(admin, req.query_params.get('link_id'))
    setting = admin.get('checkout_testing', site_id) if site_id else None
    return bool(setting and setting.get('enabled') and catalog.get('paymentTestOnly') and
                catalog.get('campaignId') == 422 and catalog.get('dollarTestSafe') and catalog.get('currency') == 'usd')


def test_catalog(catalog):
    if not (catalog.get('paymentTestOnly') and catalog.get('campaignId') == 422 and
            catalog.get('dollarTestSafe') and catalog.get('currency') == 'usd'):
        raise CatalogError('$1 testing is available only on the configured non-fulfilling payment-test campaign')
    result = copy.deepcopy(catalog)
    for option in result['options']:
        if option.get('shippable') or option.get('taxable'):
            raise CatalogError('$1 testing cannot be used for medication fulfillment')
        cycles = option.get('prepaidCycles') or 1
        if cycles not in (1, 2, 4):
            raise CatalogError('This test plan has not been verified')
        unit = format(Decimal('1.00') / cycles, '.2f')
        option.update(basePrice=unit, testUnitPrice=unit, dollarTest=True)
        if option.get('prepaidCycles'):
            option['upfrontPrice'] = '1.00'
    return result


def install_testing_admin(app, admin):
    def site(site_id):
        value = admin.get('site', site_id)
        if not value:
            raise HTTPException(404, 'Site not found')
        return value

    @app.get('/api/admin/sites/{site_id}/checkout-testing')
    def read(site_id: str, req: Request):
        admin.authenticated(req)
        value = site(site_id)
        return {'enabled': bool((admin.get('checkout_testing', site_id) or {}).get('enabled')),
                'available': value.get('campaign_id') == 422,
                'initial_total': '1.00', 'renewal_total': '1.00', 'currency': 'USD',
                'terms': '$1 initial payment and each full-term renewal. Included prepaid cycles are $0. No medication shipment.'}

    @app.put('/api/admin/sites/{site_id}/checkout-testing')
    def save(site_id: str, body: TestingSetting, req: Request):
        admin.authenticated(req, True)
        value = site(site_id)
        if value.get('campaign_id') != 422:
            raise HTTPException(422, '$1 testing is currently verified only for the existing payment-test campaign')
        admin.put('checkout_testing', site_id, {'enabled': body.enabled})
        return read(site_id, req)
