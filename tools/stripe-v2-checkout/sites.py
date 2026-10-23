"""Reviewed therapy templates and site setup, using the existing catalog publisher."""
import copy
import json
from fastapi import HTTPException, Request
from pydantic import Field, field_validator
from plans import Form, Therapy, PurchaseOption, fingerprint, ReadCache
from master import brand_campaigns
from catalog import resolve, CatalogError
from therapy_skeletons import all_skeletons, BLOCKER


class CheckoutTemplate(Form):
    id: str = Field(pattern=r'^[a-z0-9][a-z0-9-]{1,60}$')
    name: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=150)
    therapy_id: str = Field(min_length=1, max_length=61)
    purchase_option_ids: list[str] = Field(min_length=1, max_length=20)
    enabled: bool = True
    site_id: str | None = Field(default=None, max_length=61)

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
    remember_connection: bool = False


class TemplateEditor(Form):
    id: str = Field(pattern=r'^[a-z0-9][a-z0-9-]{1,60}$')
    name: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=150)
    therapy_id: str = Field(min_length=1, max_length=61)
    skeleton_id: str | None = Field(default=None, max_length=61)
    new_therapy: Therapy | None = None
    plans: list[PurchaseOption] = Field(default_factory=list, max_length=20)
    draft: bool = False
    enabled: bool = True
    site_id: str | None = Field(default=None, max_length=61)


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
    def templates_for_site(self, site_id):
        """Site-owned templates take precedence without leaking into new sites."""
        templates = self.records('checkout_template')
        owned = [t for t in templates if t.get('site_id') == site_id]
        return owned if owned else [t for t in templates if not t.get('site_id')]

    def template_state(self):
        templates = self.records('checkout_template')
        for template in templates:
            try:
                self.template_source(template)
                template['ready'] = True
            except HTTPException as exc:
                template.update(ready=False, reason=str(exc.detail))
        return templates

    def prepare_template_editor(self, payload):
        request = TemplateEditor.model_validate(payload).model_dump(mode='json')
        saved_draft = self.get('template_draft', request['id']) or {}
        if saved_draft.get('skeleton_id') and request['skeleton_id'] != saved_draft['skeleton_id']:
            raise HTTPException(422, 'Keep the master therapy skeleton attached to this draft')
        if request['skeleton_id']:
            skeleton=next((s for s in all_skeletons() if s['id']==request['skeleton_id']),None)
            if not skeleton or request['therapy_id'] != skeleton['therapy']['id']:
                raise HTTPException(422, 'Choose the matching master therapy skeleton')
            if not request['draft']:
                raise HTTPException(422, BLOCKER)
        before = self.get('checkout_template', request['id'])
        if before and before['therapy_id'] != request['therapy_id']:
            raise HTTPException(422, 'Create another template to change its therapy')
        if before and request.get('site_id') not in (None, before.get('site_id')):
            raise HTTPException(422, 'Keep this template attached to its existing site')
        view = copy.copy(self)
        original = self.get
        therapy = request['new_therapy']
        if therapy:
            existing = original('therapy', therapy['id'])
            if therapy['id'] != request['therapy_id'] or (existing and {k:v for k,v in existing.items() if k != 'revision'} != therapy):
                raise HTTPException(422, 'Choose the existing therapy or use a new name')
            therapy = existing or self.prepare_plan('therapy', therapy)[0]
        elif not original('therapy', request['therapy_id']):
            raise HTTPException(422, 'Choose a therapy or create one here')
        plans = {}
        def get(kind, key):
            if kind == 'therapy' and therapy and key == therapy['id']:
                return therapy
            if kind == 'purchase_option' and key in plans:
                return plans[key]
            return original(kind, key)
        view.get = get
        if len({p['id'] for p in request['plans']}) != len(request['plans']):
            raise HTTPException(422, 'Each plan must have a distinct identifier')
        for plan in request['plans']:
            if plan['therapy_id'] != request['therapy_id']:
                raise HTTPException(422, 'All plans must belong to this template therapy')
            # Template-owned copies keep edits away from other templates and live plans.
            key = plan['id'] if plan['id'].startswith('tpl-') and plan['id'] in (before or {}).get('purchase_option_ids', []) else 'tpl-' + fingerprint([request['id'], plan['id']])[:40]
            plan = dict(plan, id=key)
            validated = view.prepare_plan('purchase_option', plan)[0]
            old = original('purchase_option', key)
            if old and {k:v for k,v in old.items() if k != 'revision'} == {k:v for k,v in validated.items() if k != 'revision'}:
                validated['revision'] = old['revision']
            plans[key] = validated
        template = {'id':request['id'], 'name':request['name'], 'title':request['title'],
            'therapy_id':request['therapy_id'], 'purchase_option_ids':list(plans),
            'enabled':request['enabled'], 'revision':(before or {}).get('revision',0)+1}
        if (before or {}).get('site_id') or request.get('site_id'):
            template['site_id'] = (before or {}).get('site_id') or request['site_id']
        if not request['draft']:
            if not plans:
                raise HTTPException(422, 'Add at least one plan, or save this template as a draft')
            view.template_source(template)
        data = {'request':request, 'template':template, 'therapy':therapy, 'plans':list(plans.values())}
        preview = {'before':before, 'after':template, 'plans':list(plans.values()), 'stickyWrites':[],
            'draft':request['draft'], 'impact':('Saves a draft. It is not included in new sites; the current published template stays unchanged.' if request['draft'] else 'Saves this complete checkout template. New sites inherit it. Existing site checkouts keep their published settings until you review their updates.')}
        return data, [], preview, [], self.local_fingerprint()

    def finalize_template_editor(self, data):
        template = data['template']
        # One transaction prevents half-saved therapy/plan/template combinations.
        with self.store.db() as db:
            records = (([('therapy', data['therapy']['id'], data['therapy'])] if data['therapy'] else []) + [('template_draft', template['id'], data['request'])]) if data['request']['draft'] else (
                ([('therapy', data['therapy']['id'], data['therapy'])] if data['therapy'] else []) +
                [('purchase_option', p['id'], p) for p in data['plans']] +
                [('checkout_template', template['id'], template)])
            for kind, key, record in records:
                db.execute('INSERT INTO admin_config(kind,id,data) VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data', (kind,key,json.dumps(record)))
            if not data['request']['draft']:
                db.execute("DELETE FROM admin_config WHERE kind='template_draft' AND id=?", (template['id'],))

    def template_source(self, template, site=None):
        """Snapshot the approved plan and SKU metadata, with no gateway secrets."""
        therapy = self.get('therapy', template['therapy_id'])
        site = site or (self.get('site', template['site_id']) if template.get('site_id') else None)
        if not therapy or not therapy['enabled']:
            raise HTTPException(422, 'Choose an active therapy for this template')
        purchases, masters = [], {}
        for pid in template['purchase_option_ids']:
            purchase = self.get('purchase_option', pid)
            if not purchase or not purchase['enabled'] or purchase['therapy_id'] != therapy['id']:
                raise HTTPException(422, 'Choose an active plan belonging to ' + therapy['name'])
            if not purchase['skus']:
                raise HTTPException(422, purchase['name'] + ': choose at least one product, or save the template as a draft')
            for sku in purchase['skus']:
                master = self.get('master', sku) or {}
                self.therapy_for(master, therapy['id'])
                master=self.activated_master(master, (site or {}).get('brand_id'), (site or {}).get('campaign_id'))
                if not master.get('enabled') or master.get('exclude_from_campaign_setup') or master['product_duration_months'] != purchase['duration_months']:
                    raise HTTPException(422, sku + ': choose an enabled master SKU with matching product duration')
                masters[sku] = master
            purchases.append(purchase)
        return {'template': template, 'plans': purchases, 'masters': list(masters.values())}

    def prepare_site(self, kind, payload):
        if kind == 'template_editor':
            return self.prepare_template_editor(payload)
        if kind == 'checkout_template':
            data = CheckoutTemplate.model_validate(payload).model_dump(mode='json')
            before = self.get(kind, data['id'])
            if before and before['therapy_id'] != data['therapy_id']:
                raise HTTPException(422, 'Create another template to change its therapy')
            if before and data.get('site_id') not in (None, before.get('site_id')):
                raise HTTPException(422, 'Keep this template attached to its existing site')
            if before and before.get('site_id'):
                data['site_id'] = before['site_id']
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
        scope = {'id': request['id'], 'brand_id': request['brand_id'], 'campaign_id': request['campaign_id']}
        templates = [self.template_source(t, scope) for t in self.templates_for_site(request['id']) if t['enabled']]
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
        data.update(site=site, templates=templates, remember_connection=request['remember_connection'], routing_template_id=request['routing_template_id'])
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
        if any(m.get('payment_test_only') for m in source['masters']):
            data['payment_test_only']=True
            for child in data['_children']:child['payment_test_only']=True
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
        # All remote writes finished; reuse only this finalization's fresh reads.
        self = copy.copy(self)
        self.api = ReadCache(self.api)
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
        if data.get('remember_connection'):
            source = data['routing_template_id'] if isinstance(data['campaign_id'], dict) else site['campaign_id']
            self.put('site_defaults', 'default', {'id':'default', 'routing_template_id':source})
        return dict(extra, site=site['id'], checkouts=results)

    def site_state(self):
        sites = self.records('site')
        view = copy.copy(self)
        view.api = ReadCache(self.api)
        for site in sites:
            rows = []
            for template in self.templates_for_site(site['id']):
                plan = self.get('plan_checkout', checkout_id(site['id'], template['id']))
                if not plan and not template['enabled']:
                    continue
                row = {'template_id': template['id'], 'name': template['name'], 'status': 'incomplete', 'update_available': False}
                if plan:
                    row['checkout_id'] = plan['id']
                    row['customized'] = bool(plan.get('site_override'))
                    row['visibility'] = plan['visibility']
                    row['enabled'] = plan['enabled']
                    try:
                        row['update_available'] = fingerprint(self.template_source(template, site)) != plan.get('template_source_hash')
                    except HTTPException:
                        row['update_available'] = True
                    try:
                        actual = view.plan_options(*self.plan_record(plan['id']))
                        if actual['entries'] and all(e['available'] for e in actual['entries']):
                            row['status'] = 'live' if plan['visibility'] == 'public' and self.cfg.authorization_verified else 'ready'
                    except Exception:
                        pass
                    if not plan['enabled']:
                        row['status'] = 'paused'
                if row['status'] == 'incomplete':
                    try:
                        self.template_source(template, site)
                        row['reason'] = 'Check the payment connection and product availability, then review setup again.'
                    except HTTPException as exc:
                        row['reason'] = str(exc.detail)
                rows.append(row)
            site['checkouts'] = rows
        return sites
