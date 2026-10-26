"""Owner-only, brand-scoped coupon and price reviews. No payment writes."""
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from catalog import enabled, money
from master import brand_campaigns, record_campaign


class CouponInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    campaign_id: int = Field(gt=0)
    code: str = Field(min_length=2, max_length=30, pattern=r'^[A-Za-z0-9_-]+$')
    percent: int = Field(ge=1, le=99, strict=True)
    applies_to_renewals: bool = False
    expires_on: date
    timezone: str = 'America/New_York'
    max_uses: int = Field(default=100, ge=1, le=1000000)
    max_uses_per_customer: int = Field(default=0, ge=0, le=1000000)

    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('Choose an IANA timezone') from None
        return value


class CouponProposal(CouponInput):
    brand_id: str


class PriceInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    expected_price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


def brand_scope(admin, brand_id, campaign_id=None, exclusive=False):
    brand = admin.get('brand', brand_id)
    if not brand:
        raise HTTPException(404, 'Brand not found')
    if campaign_id is not None and campaign_id not in brand_campaigns(brand):
        raise HTTPException(404, 'Campaign is not assigned to this brand')
    if exclusive and any(b['id'] != brand_id and campaign_id in brand_campaigns(b)
                         for b in admin.records('brand')):
        raise HTTPException(409, 'This campaign is shared by brands. Assign a dedicated campaign before creating brand-only coupons.')
    return brand


def coupon_summary(profile, campaign_id):
    # Explicit allowlist: never expose provider creator records or raw responses.
    expiry = profile.get('expires_at') or {}
    return {'id': int(profile['id']), 'campaign_id': campaign_id,
            'name': str(profile.get('name', '')),
            'percent': str(profile.get('discount_percent', profile.get('discount_pct', 0))),
            'applies_to_renewals': enabled(profile.get('is_lifetime')),
            'active': enabled(profile.get('is_active')),
            'expires_at': expiry.get('date', '') if isinstance(expiry, dict) else str(expiry),
            'timezone': expiry.get('timezone', '') if isinstance(expiry, dict) else '',
            'use_count': profile.get('use_count', 0),
            'max_uses': (profile.get('limits') or {}).get('total', 0),
            'codes': [str(p.get('code', '')) for p in profile.get('promo_codes', [])
                      if enabled(p.get('is_active')) and not enabled(p.get('is_deleted'))]}


def prepare_coupon(admin, raw):
    data = CouponProposal.model_validate(raw).model_dump(mode='json')
    data['code'] = data['code'].upper()
    cid = data['campaign_id']
    brand_scope(admin, data['brand_id'], cid, exclusive=True)
    if date.fromisoformat(data['expires_on']) <= datetime.now(ZoneInfo(data['timezone'])).date():
        raise HTTPException(422, 'Choose a future expiration date. The code expires at the start of that date.')
    with admin.store.db() as db:
        pending = db.execute("SELECT data FROM admin_reviews WHERE kind='coupon' AND status IN ('applying','reconcile')").fetchall()
    import json
    for row in pending:
        held = json.loads(row[0])['data']
        if held['brand_id'] == data['brand_id'] and held['campaign_id'] == cid:
            raise HTTPException(409, 'A coupon change for this campaign needs reconciliation. Inspect its recorded objects before creating another.')
    from admin import fingerprint
    campaign_path = f'/api/v2/campaigns/{cid}'
    campaign = admin.api.detail(campaign_path)
    if enabled(campaign.get('is_archived')):
        raise HTTPException(422, 'This campaign is archived')
    guards = [{'path': campaign_path, 'keys': ['id', 'coupon_profiles', 'is_archived'],
               'hash': fingerprint({k: campaign.get(k) for k in ('id', 'coupon_profiles', 'is_archived')})}]
    for profile in campaign.get('coupon_profiles', []):
        details = admin.api.detail('/api/v2/coupons/' + str(int(profile['id'])))
        if any(str(p.get('code', '')).upper() == data['code'] for p in details.get('promo_codes', [])):
            raise HTTPException(409, 'This code already belongs to a coupon on this campaign. Choose a new code.')
    payload = {'name': data['code'], 'description': 'Brand coupon: ' + data['brand_id'],
               'type_id': 1, 'minimum_purchase': 0, 'is_lifetime': int(data['applies_to_renewals']),
               'is_free_shipping': 0,
               'expiration': {'date': data['expires_on'], 'timezone': data['timezone']},
               'limits': {'total': data['max_uses'], 'per_code': data['max_uses'],
                          'per_customer': data['max_uses_per_customer'],
                          'per_code_per_customer': data['max_uses_per_customer']},
               'promo_codes': [{'code': data['code']}],
               'discount': {'type_id': 34, 'behavior_type_id': 36, 'percent': data['percent']}}
    operations = [
        {'method': 'POST', 'path': '/api/v2/coupons', 'body': payload, 'save': 'coupon'},
        {'method': 'PUT', 'path': campaign_path, 'coupon_assignment': True,
         'preserve_coupons': [int(p['id']) for p in campaign.get('coupon_profiles', [])],
         'body': {'coupon_profile_id': {'$ref': 'coupon'}}},
    ]
    preview = {'before': {}, 'after': data, 'stickyWrites': operations,
               'impact': 'Creates a new percentage coupon and adds it only to this brand campaign. '
                         'Existing coupons, prices and subscription orders are preserved. '
                         'Each separate cart order counts as a use. Expiration limits new applications; '
                         'a renewal discount continues on subscriptions that already redeemed it.'}
    return data, guards, preview, operations, admin.local_fingerprint()


def verify_coupon(profile, data):
    expiry = profile.get('expires_at') or {}
    limits = profile.get('limits') or {}
    codes = [p for p in profile.get('promo_codes', []) if str(p.get('code', '')).upper() == data['code']
             and enabled(p.get('is_active')) and not enabled(p.get('is_deleted'))]
    valid = (int(profile.get('type_id', 0)) == 1 and enabled(profile.get('is_active'))
             and not enabled(profile.get('is_bogo')) and not enabled(profile.get('is_free_shipping'))
             and money(profile.get('discount_percent', profile.get('discount_pct', 0))) == Decimal(data['percent'])
             and enabled(profile.get('is_lifetime')) == data['applies_to_renewals']
             and bool(codes) and isinstance(expiry, dict)
             and str(expiry.get('date', '')).split(' ')[0] == data['expires_on']
             and expiry.get('timezone') == data['timezone']
             and all(int(limits.get(k, -1)) == v for k, v in {
                 'total': data['max_uses'], 'per_code': data['max_uses'],
                 'per_customer': data['max_uses_per_customer'],
                 'per_code_per_customer': data['max_uses_per_customer']}.items()))
    if not valid:
        raise ValueError('Coupon read-back differs from the approved terms')


def register_commerce(admin, app):
    @app.get('/api/admin/brands/{brand_id}/commerce/openapi.json', include_in_schema=False)
    def commerce_schema(brand_id: str, req: Request):
        """Owner-authenticated contract; never part of public storefront Swagger."""
        import copy
        admin.authenticated(req)
        brand=brand_scope(admin,brand_id)
        schema=app.openapi()
        paths={}
        for path,item in schema['paths'].items():
            if not path.startswith('/api/admin/brands/{brand_id}/') and path!='/api/admin/apply':continue
            value=copy.deepcopy(item)
            for method,operation in value.items():
                operation['parameters']=[p for p in operation.get('parameters',[]) if p.get('name')!='brand_id']
                operation['security']=[{'adminSession':[],**({'csrfToken':[]} if method!='get' else {})}]
            paths[path.replace('{brand_id}',brand_id)]=value
        return {'openapi':'3.1.0','info':{'title':brand['name']+' · Prices and coupons','version':'1.0.0',
                'description':'Owner-only APIs. POST reviews prepares a preview; POST /api/admin/apply explicitly approves it. Existing subscription prices are preserved.'},
                'paths':paths,'components':{'schemas':schema.get('components',{}).get('schemas',{}),
                'securitySchemes':{'adminSession':{'type':'apiKey','in':'cookie','name':'__Host-admin'},
                                   'csrfToken':{'type':'apiKey','in':'header','name':'X-CSRF-Token'}}}}

    @app.get('/api/admin/brands/{brand_id}/prices', tags=['Brand pricing'])
    def prices(brand_id: str, req: Request):
        admin.authenticated(req)
        brand = brand_scope(admin, brand_id)
        return {'brand_id': brand_id, 'prices': [
            {k: o.get(k) for k in ('id', 'sku', 'name', 'price', 'billing_models', 'configuration')} |
            {'campaign_id': record_campaign(o, brand)}
            for o in admin.records('offering') if o['brand_id'] == brand_id]}

    @app.post('/api/admin/brands/{brand_id}/prices/{offering_id}/reviews', tags=['Brand pricing'])
    def price_review(brand_id: str, offering_id: str, body: PriceInput, req: Request):
        admin.authenticated(req, True)
        from admin import LOCK
        with LOCK:
            brand = brand_scope(admin, brand_id)
            old = admin.get('offering', offering_id)
            if not old or old['brand_id'] != brand_id:
                raise HTTPException(404, 'Price not found for this brand')
            if money(old['price']) != body.expected_price:
                raise HTTPException(409, 'This price changed. Reload before editing.')
            if body.price == body.expected_price:
                raise HTTPException(422, 'Enter a different price')
            data = {k: old[k] for k in ('id', 'brand_id', 'sku', 'name', 'billing_models', 'configuration') if k in old}
            data.update(campaign_id=record_campaign(old, brand), price=str(body.price))
            return admin.create_review('offer', data)

    @app.get('/api/admin/brands/{brand_id}/coupons', tags=['Brand coupons'])
    def coupons(brand_id: str, campaign_id: int, req: Request):
        admin.authenticated(req)
        brand_scope(admin, brand_id, campaign_id)
        campaign = admin.api.detail(f'/api/v2/campaigns/{campaign_id}')
        return {'brand_id': brand_id, 'campaign_id': campaign_id, 'coupons': [
            coupon_summary(admin.api.detail('/api/v2/coupons/' + str(int(p['id']))), campaign_id)
            for p in campaign.get('coupon_profiles', [])]}

    @app.post('/api/admin/brands/{brand_id}/coupons/reviews', tags=['Brand coupons'])
    def coupon_review(brand_id: str, body: CouponInput, req: Request):
        admin.authenticated(req, True)
        return admin.create_review('coupon', body.model_dump(mode='json') | {'brand_id': brand_id})
