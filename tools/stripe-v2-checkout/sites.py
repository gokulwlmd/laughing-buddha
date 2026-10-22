"""Reviewed therapy templates and site setup, using the existing catalog publisher."""
import copy
import json
from fastapi import HTTPException, Request
from pydantic import Field, field_validator
from plans import Form, fingerprint, ReadCache
from master import brand_campaigns
from catalog import resolve, CatalogError


class CheckoutTemplate(Form):
    id: str = Field(pattern=r'^[a-z0-9][a-z0-9-]{1,60}$')
    name: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=150)
    therapy_id: str = Field(min_length=1, max_length=61)
    purchase_option_ids: list[str] = Field(min_length=1, max_length=20)
    enabled: bool = True

    @field_validator('purchase_option_ids')
    @classmethod
    def unique(cls, values):
        if len(set(values)) != len(values):
            raise ValueError('Choose each plan once')
        return values


class Site(Form):
    id: str = Field(pattern=r'^[a-z0-9][a-z0-9-]{1,60}$')
    name: str = Field(min_length=1, max_length=100)
    brand_id: str = Field(min_length=1, max_length=61)
    campaign_id: int | None = Field(default=None, gt=0)
    campaign_name: str = Field(default='', max_length=100)
    routing_template_id: int = Field(default=422, gt=0)
    # A new brand can be reviewed together with site setup; existing brands are immutable here.
    new_brand: dict | None = None


class SiteCheckout(Form):
    site_id: str = Field(min_length=1, max_length=61)
    template_id: str = Field(min_length=1, max_length=61)
    title: str = Field(min_length=1, max_length=150)
    purchase_option_ids: list[str] = Field(min_length=1, max_length=20)
    payment_types: list[str] = Field(min_length=1, max_length=3)
    visibility: str = Field(pattern=r'^(public|private)$')
    enabled: bool = True

    @field_validator('purchase_option_ids', 'payment_types')
    @classmethod
    def unique(cls, values):
        if len(set(values)) != len(values):
            raise ValueError('Choose each item once')
        return values

    @field_validator('payment_types')
    @classmethod
    def types(cls, values):
        if not set(values).issubset({'once', 'subscription', 'prepaid'}):
            raise ValueError('Choose supported payment choices')
        return values


def checkout_id(site_id, template_id):
    return 'site-' + fingerprint([site_id, template_id])[:40]


class SiteCatalog:
    def template_source(self, template):
        """Snapshot the approved plan and SKU metadata, with no gateway secrets."""
        therapy = self.get('therapy', template['therapy_id'])
        if not therapy or not therapy['enabled']:
            raise HTTPException(422, 'Choose an active therapy for this template')
        purchases, masters = [], {}
        for pid in template['purchase_option_ids']:
            purchase = self.get('purchase_option', pid)
            if not purchase or not purchase['enabled'] or purchase['therapy_id'] != therapy['id'] or not purchase['skus']:
                raise HTTPException(422, 'Each template plan needs active matching-duration master SKUs')
            for sku in purchase['skus']:
                master = self.get('master', sku) or {}
                self.therapy_for(master, therapy['id'])
                if not master.get('enabled') or master.get('exclude_from_campaign_setup') or master['product_duration_months'] != purchase['duration_months']:
                    raise HTTPException(422, sku + ': choose an enabled master SKU with matching product duration')
                masters[sku] = master
            purchases.append(purchase)
        return {'template': template, 'plans': purchases, 'masters': list(masters.values())}

    def prepare_site(self, kind, payload):
        if kind == 'checkout_template':
            data = CheckoutTemplate.model_validate(payload).model_dump(mode='json')
            before = self.get(kind, data['id'])
            if before and before['therapy_id'] != data['therapy_id']:
                raise HTTPException(422, 'Create another template to change its therapy')
            data['revision'] = (before or {}).get('revision', 0) + 1
            source = self.template_source(data)
            return data, [], {'before': before, 'after': data, 'plans': source['plans'], 'stickyWrites': [],
                'impact': 'Saves a reusable therapy checkout. Existing site checkouts keep their published settings until their update is reviewed.'}, [], self.local_fingerprint()
        if kind == 'site_checkout':
            override = SiteCheckout.model_validate(payload).model_dump(mode='json')
            site = self.get('site', override['site_id'])
            template = self.get('checkout_template', override['template_id'])
            old = self.get('plan_checkout', checkout_id(override['site_id'], override['template_id']))
            if not site or not template or not old:
                raise HTTPException(422, 'Prepare this site checkout first')
            # Customize the published snapshot, not an unreviewed new template revision.
            snapshot = old['template_snapshot']
            if not set(override['purchase_option_ids']).issubset(snapshot['template']['purchase_option_ids']):
                raise HTTPException(422, 'Select plans in the published template or review its update first')
            data, guards, preview, ops, local = self.site_plan(site, snapshot, override)
            preview['impact'] = 'Customizes only this site checkout. Its URL and independent campaign prices are preserved. No Sticky writes or subscription changes.'
            return data, guards, preview, ops, local

        request = Site.model_validate(payload).model_dump(mode='json')
        before = self.get('site', request['id'])
        if before and (request['brand_id'] != before['brand_id'] or request['campaign_id'] != before['campaign_id']):
            raise HTTPException(422, 'A site keeps its brand, campaign and published URLs. Create another site to use a different connection.')
        if request['campaign_id'] and any(s['id'] != request['id'] and s['brand_id'] == request['brand_id'] and s['campaign_id'] == request['campaign_id'] for s in self.records('site')):
            raise HTTPException(409, 'This brand/campaign already belongs to a site. Use a separate campaign for independent site prices.')
        with self.store.db() as db:
            held = db.execute("SELECT data,result FROM admin_reviews WHERE kind='site' AND status IN ('applying','reconcile')").fetchall()
        for raw, result in held:
            prior = json.loads(raw)['request']; created = json.loads(result or '{}').get('created', {})
            if prior['id'] == request['id'] or (request['campaign_id'] and request['campaign_id'] in (prior.get('campaign_id'), created.get('campaign'))) or (not request['campaign_id'] and prior.get('campaign_name') == request['campaign_name']):
                raise HTTPException(409, 'This site setup needs reconciliation. Inspect its recorded objects before preparing another review.')
        templates = [self.template_source(t) for t in self.records('checkout_template') if t['enabled']]
        if not templates:
            raise HTTPException(422, 'Save an enabled checkout template with assigned plans first')
        skus = list(dict.fromkeys(m['sku'] for source in templates for m in source['masters']))
        brand = self.get('brand', request['brand_id'])
        if request['new_brand'] is not None:
            from admin import Brand
            if brand:
                raise HTTPException(422, 'Edit an existing brand in Advanced before site setup')
            brand = Brand.model_validate(request['new_brand']).model_dump(mode='json')
            if brand['id'] != request['brand_id'] or brand_campaigns(brand):
                raise HTTPException(422, 'A new site brand must use its selected identifier with no existing campaign mapping')
        if not brand:
            raise HTTPException(422, 'Select a brand or enter a new brand design')
        setup = {'brand_id': brand['id'], 'campaign_id': request['campaign_id'], 'name': request['campaign_name'], 'template_id': request['routing_template_id']}
        data, guards, preview, ops, local = self.prepare_setup(setup, required_skus=skus, site_brand=brand)
        site = {k: request[k] for k in ('id', 'name', 'brand_id')}
        site['campaign_id'] = data['campaign_id']
        site['revision'] = (before or {}).get('revision', 0) + 1
        data.update(site=site, templates=templates)
        preview.update(before=before, after=site, brand=brand, templates=templates,
            impact='Prepares every enabled therapy template for this site after approval. Inherits brand design and preserves existing campaign prices, URLs, site overrides and subscriptions. New links start private. Catalog read-back must pass before a checkout becomes ready; incomplete setup never activates a link.')
        affected = set(preview.get('affectedCheckoutLinks', []))
        for plan in self.records('plan_checkout'):
            if plan.get('site_id') == site['id']:
                affected.update(l['id'] for l in self.records('link') if l.get('plan_checkout_id') == plan['id'])
        preview['affectedCheckoutLinks'] = sorted(affected)
        return data, guards, preview, ops, local

    def site_plan(self, site, source, override=None):
        template = source['template']; key = checkout_id(site['id'], template['id'])
        old = self.get('plan_checkout', key)
        if old and (old.get('site_id') != site['id'] or old.get('template_id') != template['id']):
            raise HTTPException(409, 'This checkout identifier is already in use')
        override = override if override is not None else (old or {}).get('site_override')
        purchase_ids = (override or {}).get('purchase_option_ids', template['purchase_option_ids'])
        if not set(purchase_ids).issubset(template['purchase_option_ids']):
            raise HTTPException(422, 'A customized plan was removed from this template. Adjust the site customization before applying its update.')
        # Use a request-local view of the reviewed snapshots. Never rewrite shared plans.
        view = copy.copy(self)
        originals = self.get
        snapshots = {p['id']: p for p in source['plans']}
        payment_types = (override or {}).get('payment_types', ['once', 'subscription', 'prepaid'])
        def get(kind, identifier):
            if kind == 'purchase_option' and identifier in snapshots:
                p = copy.deepcopy(snapshots[identifier])
                p['payment_types'] = [t for t in p['payment_types'] if t in payment_types]
                if not p['payment_types']:
                    raise HTTPException(422, p['name'] + ': enable at least one template payment choice')
                return p
            return originals(kind, identifier)
        view.get = get
        request = {'id': key, 'brand_id': site['brand_id'], 'campaign_id': site['campaign_id'], 'therapy_id': template['therapy_id'],
            'title': (override or {}).get('title', template['title']), 'purchase_option_ids': purchase_ids,
            'visibility': (override or {}).get('visibility', (old or {}).get('visibility', 'private')),
            'enabled': (override or {}).get('enabled', True)}
        data, guards, preview, ops, local = view.prepare_plan('plan_checkout', request)
        data.update(site_id=site['id'], template_id=template['id'], template_snapshot=source,
            template_source_hash=fingerprint(source), site_override=override)
        # Repeated setup must not rotate private invitations or invalidate fresh quotes.
        if old:
            comparable = lambda p: {k:v for k,v in p.items() if k not in ('revision', '_children')}
            if comparable(data) == comparable(old):
                data['revision'] = old['revision']
                for child in data['_children']:
                    previous = self.get('link', child['id'])
                    if previous and comparable(child) == comparable(previous):
                        child['revision'] = previous['revision']
        return data, guards, preview, ops, local

    def finalize_site(self, data, references):
        extra = self.finalize_master('campaign_setup', data, references)
        site = references(data['site'])
        # Save incomplete setup too, so a retry reuses the recorded campaign and offers.
        self.put('site', site['id'], site)
        results = []
        for source in data['templates']:
            try:
                plan, _, _, _, _ = self.site_plan(site, source)
                self.finalize_plan('plan_checkout', plan)
                results.append({'template_id': source['template']['id'], 'status': 'ready'})
            except Exception:
                results.append({'template_id': source['template']['id'], 'status': 'incomplete', 'reason': 'Check campaign access, assigned billing choices, matching SKU durations and site customizations before activating.'})
        self.put('site', site['id'], dict(site, checkouts=results))
        return dict(extra, site=site['id'], checkouts=results)

    def site_state(self):
        sites = self.records('site')
        view = copy.copy(self)
        view.api = ReadCache(self.api)
        for site in sites:
            rows = []
            for template in self.records('checkout_template'):
                plan = self.get('plan_checkout', checkout_id(site['id'], template['id']))
                if not plan and not template['enabled']:
                    continue
                row = {'template_id': template['id'], 'name': template['name'], 'status': 'incomplete', 'update_available': False}
                if plan:
                    row['checkout_id'] = plan['id']
                    row['customized'] = bool(plan.get('site_override'))
                    try:
                        row['update_available'] = fingerprint(self.template_source(template)) != plan.get('template_source_hash')
                    except HTTPException:
                        row['update_available'] = True
                    try:
                        actual = view.plan_options(*self.plan_record(plan['id']))
                        if actual['entries'] and all(e['available'] for e in actual['entries']):
                            row['status'] = 'live' if plan['visibility'] == 'public' and self.cfg.authorization_verified else 'ready'
                    except Exception:
                        pass
                rows.append(row)
            site['checkouts'] = rows
        return sites
