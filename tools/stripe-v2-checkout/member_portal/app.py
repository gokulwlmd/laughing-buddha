from typing import Union
"""Member APIs: explicit order grants, real Sticky state, and local care requests.

This module never creates a charge, shipment, prescription, or simulated order.
Question and messaging adapters remain explicitly disconnected placeholders.
"""
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
import threading
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from patient_demo.app import clean_answers, visible, IntakePatch, IntakeSubmit, IntakeResponse, MessageBody
from patient_demo.provider import get_template, THERAPIES as QUESTION_THERAPIES
from .provider import StickyOrderProvider, ProviderError, ProviderUncertain, ProviderRejected
from .care import CareManager, CarePlan
from .claims import ClaimsManager
from .notifications import NotificationsResult, order_notifications
from refill_rules import RefillRules, SaveRefillRules, site_rule_key

HERE = Path(__file__).parent
SESSION_SECONDS = 86400
INVITE_SECONDS = 3600


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def encoded(value):
    return json.dumps(value, separators=(',', ':'), sort_keys=True, allow_nan=False)


def identifier(kind):
    return kind + '_' + secrets.token_urlsafe(18)


def stamp(now):
    return datetime.fromtimestamp(now, timezone.utc).isoformat().replace('+00:00', 'Z')


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()


class Form(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Login(Form):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class Enrollment(Form):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    invite_token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=12, max_length=256)


class ReceiptEnrollment(Form):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    password: str = Field(min_length=12, max_length=256)


class ClaimInvite(Form):
    invite_token: str = Field(min_length=20, max_length=200)


class SyncBody(Form):
    allow_import: bool = False
    allow_historical: bool = False
    order_ids: list[str] = Field(default_factory=list, max_length=50)


class InviteBody(Form):
    order_id: str = Field(min_length=1, max_length=40, pattern=r'^\d+$')


class ActionBody(Form):
    client_request_id: str = Field(min_length=8, max_length=100, pattern=r'^[A-Za-z0-9_-]+$')


class RefillBody(ActionBody):
    task_id: str | None = Field(default=None, max_length=80, pattern=r'^[a-z0-9-]+$')
    kind: str = Field(default='scheduled', pattern=r'^(scheduled|early)$')
    reason: str = Field(default='', max_length=1000)
    order_id: str = Field(min_length=1, max_length=40, pattern=r'^\d+$')
    sku: str = Field(min_length=1, max_length=200)


class ShippingAddress(Form):
    first_name: str = Field(min_length=1, max_length=64)
    last_name: str = Field(min_length=1, max_length=64)
    address: str = Field(min_length=2, max_length=150)
    address2: str = Field(default='', max_length=150)
    city: str = Field(min_length=1, max_length=80)
    region: str = Field(pattern=r'^[A-Z]{2}$')
    postal_code: str = Field(pattern=r'^\d{5}(?:-\d{4})?$')
    country: str = Field(pattern=r'^US$')


class AddressBody(ActionBody):
    address: ShippingAddress


class ReviewRefill(Form):
    revision: StrictInt = Field(ge=0)
    status: str = Field(pattern=r'^(needs_information|reviewed|declined)$')
    note: str = Field(default='', max_length=1000)


class PatientModel(BaseModel):
    id: str
    name: str
    email: str


class SiteModel(BaseModel):
    id: str
    name: str
    color: str
    logo_url: str = ''
    support_email: str = ''
    theme: str = 'default'


class TherapyModel(BaseModel):
    id: str
    name: str


class ConfigurationResult(BaseModel):
    site: SiteModel
    therapies: list[TherapyModel]
    intake_provider_connected: bool
    messaging_provider_connected: bool


class CapabilityResult(BaseModel):
    available: bool
    reason: str


class AuthResult(BaseModel):
    access_token: str
    expires_at: str
    patient: PatientModel
    site: SiteModel


class MeResult(BaseModel):
    patient: PatientModel
    site: SiteModel


class SubscriptionModel(BaseModel):
    id: str
    product_id: str
    status: str
    next_billing_date: str | None = None
    next_cycle_date: str | None = None
    billing_interval_days: int | None = None
    prepaid_renews: bool | None = None
    actions: list[str]
    address_update_available: bool = False
    shipping_address: dict | None = None


class RefillAvailability(BaseModel):
    task_id: str | None = None
    eligible: bool
    reason: str
    next_date: str | None = None
    test_only: bool
    early_allowed: bool = False
    early_reason: str = ''
    early_next_date: str | None = None
    additional_purchase_may_be_required: bool = False


class OrderModel(BaseModel):
    order_role: str = 'initial'
    intake_kind: str = 'initial'
    journey: dict | None = None
    dry_run: bool = False
    care_plan: CarePlan | None = None
    id: str
    number: str
    site_id: str
    therapy_id: str
    therapy_name: str
    product_name: str
    sku: str
    plan_name: str
    total: str
    currency: str | None
    payment_status: str
    intake_status: str
    medical_status: str
    fulfillment_status: str
    tracking_number: str | None = None
    shipping_date: str | None = None
    created_at: str | None
    last_synced_at: str
    subscriptions: list[SubscriptionModel]
    refill: RefillAvailability
    test_only: bool
    address_update_available: bool = False
    shipping_address: dict | None = None


class OrdersResult(BaseModel):
    orders: list[OrderModel]


class StorePlan(BaseModel):
    sku: str = ''
    recurring: bool | None = None
    plan_id: str
    checkout_id: str
    therapy_id: str
    therapy_name: str
    product_name: str
    plan_name: str
    total: str
    currency: str
    checkout_url: str
    payment_test_only: bool = False


class StoreResult(BaseModel):
    site: SiteModel
    plans: list[StorePlan]
    unavailable_therapies: list[str] = Field(default_factory=list)


class MemberIntakeResponse(IntakeResponse):
    task_id: str | None = None
    provider_connected: bool = False


class CareMessage(BaseModel):
    id: str
    sender: str
    body: str
    created_at: str
    client_message_id: str
    automated: bool


class MessagesResult(BaseModel):
    messages: list[CareMessage]
    provider_connected: bool = False


class MessageDraft(BaseModel):
    body: str = ''
    revision: int = 0
    updated_at: str | None = None
    provider_connected: bool = False


class MessageDraftSave(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    body: str = Field(max_length=2000)
    revision: StrictInt = Field(ge=0)


class RefillModel(BaseModel):
    task_id: str | None = None
    simulated: bool = False
    id: str
    order_id: str
    sku: str
    status: str
    revision: int
    created_at: str
    updated_at: str
    test_only: bool
    rule_revision: int
    kind: str = 'scheduled'
    reason: str = ''
    clinical_approval: bool = False
    fulfillment_created: bool = False


class RefillsResult(BaseModel):
    requests: list[RefillModel]


class RefillResult(BaseModel):
    request: RefillModel


def install(app, admin, store, cfg, receipt_access=None, clock=time.time, provider=None):
    service = MemberService(admin, store, cfg, clock, provider or StickyOrderProvider(admin.api))
    service.attach(app, receipt_access)
    app.state.member_portal = service
    return service


class MemberService:
    identity_init_lock = threading.Lock()
    def __init__(self, admin, store, cfg, clock, provider):
        self.admin, self.store, self.cfg, self.clock, self.provider = admin, store, cfg, clock, provider
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS member_patients(
                    id TEXT PRIMARY KEY,site_id TEXT NOT NULL,customer_id TEXT NOT NULL,
                    name TEXT NOT NULL,email TEXT NOT NULL,salt TEXT NOT NULL,password_hash TEXT NOT NULL,
                    identity_source TEXT NOT NULL,created REAL NOT NULL,
                    UNIQUE(site_id,email),UNIQUE(site_id,customer_id));
                CREATE TABLE IF NOT EXISTS member_sessions(
                    token_hash TEXT PRIMARY KEY,site_id TEXT NOT NULL,patient_id TEXT NOT NULL,expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS member_orders(
                    site_id TEXT NOT NULL,order_id TEXT NOT NULL,customer_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,therapy_id TEXT NOT NULL,sku TEXT NOT NULL,
                    snapshot TEXT NOT NULL,payload TEXT NOT NULL,synced REAL NOT NULL,
                    PRIMARY KEY(site_id,order_id));
                CREATE UNIQUE INDEX IF NOT EXISTS member_order_unique_site ON member_orders(order_id);
                CREATE TABLE IF NOT EXISTS member_grants(
                    site_id TEXT NOT NULL,order_id TEXT NOT NULL,patient_id TEXT NOT NULL,
                    created REAL NOT NULL,source TEXT NOT NULL,PRIMARY KEY(site_id,order_id));
                CREATE TABLE IF NOT EXISTS member_invites(
                    token_hash TEXT PRIMARY KEY,site_id TEXT NOT NULL,order_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,created REAL NOT NULL,expires REAL NOT NULL,used REAL);
                CREATE TABLE IF NOT EXISTS member_auth_failures(site_id TEXT NOT NULL,identity_hash TEXT NOT NULL,created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS member_intakes(
                    id TEXT PRIMARY KEY,site_id TEXT NOT NULL,order_id TEXT NOT NULL,patient_id TEXT NOT NULL,
                    status TEXT NOT NULL,revision INTEGER NOT NULL,answers TEXT NOT NULL,current_step INTEGER NOT NULL,
                    template TEXT NOT NULL,updated REAL NOT NULL,submitted REAL,submitted_answers TEXT,
                    UNIQUE(site_id,order_id,patient_id));
                CREATE TABLE IF NOT EXISTS member_messages(
                    id TEXT PRIMARY KEY,site_id TEXT NOT NULL,patient_id TEXT NOT NULL,sender TEXT NOT NULL,
                    body TEXT NOT NULL,created REAL NOT NULL,client_message_id TEXT NOT NULL,
                    UNIQUE(site_id,patient_id,client_message_id,sender));
                CREATE TABLE IF NOT EXISTS member_message_drafts(
                    site_id TEXT NOT NULL,patient_id TEXT NOT NULL,body TEXT NOT NULL,
                    revision INTEGER NOT NULL,updated REAL NOT NULL,
                    PRIMARY KEY(site_id,patient_id));
                CREATE TABLE IF NOT EXISTS member_notification_reads(
                    site_id TEXT NOT NULL,patient_id TEXT NOT NULL,notification_id TEXT NOT NULL,
                    created REAL NOT NULL,PRIMARY KEY(site_id,patient_id,notification_id));
                CREATE TABLE IF NOT EXISTS member_refills(
                    id TEXT PRIMARY KEY,site_id TEXT NOT NULL,patient_id TEXT NOT NULL,order_id TEXT NOT NULL,
                    sku TEXT NOT NULL,cycle_key TEXT NOT NULL,status TEXT NOT NULL,revision INTEGER NOT NULL,
                    rule TEXT NOT NULL,test_only INTEGER NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,note TEXT NOT NULL,
                    client_request_id TEXT NOT NULL,kind TEXT NOT NULL DEFAULT 'scheduled',reason TEXT NOT NULL DEFAULT '',UNIQUE(site_id,patient_id,client_request_id));
                CREATE TABLE IF NOT EXISTS member_actions(
                    id TEXT PRIMARY KEY,site_id TEXT NOT NULL,patient_id TEXT NOT NULL,order_id TEXT NOT NULL,
                    subscription_id TEXT NOT NULL,action TEXT NOT NULL,client_request_id TEXT NOT NULL,
                    status TEXT NOT NULL,created REAL NOT NULL,UNIQUE(site_id,patient_id,client_request_id));
            ''')
            existing_columns = {r[1] for r in db.execute('PRAGMA table_info(member_refills)')}
            if 'kind' not in existing_columns:
                db.execute("ALTER TABLE member_refills ADD COLUMN kind TEXT NOT NULL DEFAULT 'scheduled'")
            if 'reason' not in existing_columns:
                db.execute("ALTER TABLE member_refills ADD COLUMN reason TEXT NOT NULL DEFAULT ''")

        from .answer_profile import AnswerProfile
        from refill_rules import migrate_claim_window
        migrate_claim_window(self.store)
        self.answer_profile = AnswerProfile(self)
        from .wlmd import IdentityChecks
        self.identity_checks = IdentityChecks(self)
        from .id_uploads import IDUploads
        self.id_uploads = IDUploads(self)
        self.care = CareManager(self)
        self.claims = ClaimsManager(self)
        from .renewals import RenewalsManager
        self.renewals = RenewalsManager(self)
        from .upgrades import Upgrades
        self.upgrades = Upgrades(self)
        self._store_cache = {}

    def db(self):
        db = self.store.db()
        db.row_factory = sqlite3.Row
        return db

    @property
    def identity(self):
        if os.environ.get('MEMBER_IDENTITY_PROVIDER') != 'sticky':
            return None
        with self.identity_init_lock:
            if not hasattr(self, '_sticky_identity'):
                from .identity import StickyIdentity
                self._sticky_identity = StickyIdentity(self)
        return self._sticky_identity

    def authenticate_password(self, site_id, email, password):
        email = email.strip().lower()
        identity = digest(site_id + ':' + email)
        with self.db() as db:
            db.execute('DELETE FROM member_auth_failures WHERE created<?', (self.clock() - 900,))
            failures = db.execute('SELECT COUNT(*) FROM member_auth_failures WHERE site_id=? AND identity_hash=?', (site_id, identity)).fetchone()[0]
        if failures >= 10:
            raise HTTPException(429, 'Too many sign-in attempts. Please try again later.')
        try:
            return self.identity.login(email, password)
        except HTTPException as exc:
            if exc.status_code == 401:
                with self.db() as db:
                    db.execute('INSERT INTO member_auth_failures VALUES(?,?,?)', (site_id, identity, self.clock()))
            raise

    def receipt_account(self, row, password=None):
        if not self.identity:
            raise HTTPException(503, 'Sticky member accounts are not enabled yet.')
        order, _ = self.receipt_order(row)
        email = json.loads(order['payload'])['customer']['email'].strip().lower()
        site_id = order['site_id']
        result = {'site_id': site_id, 'provider': 'sticky', 'password_min_length': 12,
                  'portal_url': self.cfg.public_url + '/portal/' + site_id}
        if password is None:
            result['state'] = self.identity.setup_state(email, site_id, order['order_id'])
            return result
        # Existing identity is never overwritten. The provider only uses the
        # temporary secret it created for this exact receipt, or authenticates.
        auth = self.enroll(site_id, order, password, 'checkout_receipt')
        # A single-use, site-bound handoff keeps the Sticky token and password
        # server-side. The browser never puts a reusable session in a URL.
        token = secrets.token_urlsafe(32)
        expires = min(self.clock() + 1800, datetime.fromisoformat(auth['expires_at'].replace('Z', '+00:00')).timestamp())
        with self.db() as db:
            db.execute('INSERT INTO member_identity_sessions VALUES(?,?,?)',
                (digest('handoff:' + token), self.identity.encrypt(encoded({'purpose': 'portal_handoff', 'site_id': site_id, 'auth': auth})), expires))
        return result | {'state': 'ready', 'portal_handoff': token, 'handoff_expires_at': stamp(expires)}

    def consume_handoff(self, site_id, token):
        if not self.identity or not isinstance(token, str) or not 20 <= len(token) <= 100:
            raise HTTPException(401, 'Please sign in to your member portal.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM member_identity_sessions WHERE session_hash=?', (digest('handoff:' + token),)).fetchone()
            if not row or row['checked'] <= self.clock():
                raise HTTPException(401, 'This sign-in link expired. Sign in with the password you just created.')
            payload = json.loads(self.identity.decrypt(row['secret']))
            if payload.get('purpose') != 'portal_handoff' or payload.get('site_id') != site_id:
                raise HTTPException(401, 'This sign-in link belongs to another site.')
            auth = payload['auth']
            session = db.execute('SELECT * FROM member_sessions WHERE token_hash=? AND site_id=? AND expires>?',
                (digest(auth['access_token']), site_id, self.clock())).fetchone()
            if not session:
                raise HTTPException(401, 'Please sign in again.')
            db.execute('DELETE FROM member_identity_sessions WHERE session_hash=?', (digest('handoff:' + token),))
        self.identity.check_session(digest(auth['access_token']), force=True)
        return auth

    def site(self, site_id):
        site = self.admin.get('site', site_id)
        if not site:
            raise HTTPException(404, 'Site not found')
        brand = self.admin.get('brand', site['brand_id']) or {}
        # Named themes are presentation only. Site/order ownership still uses
        # the saved site ID; a brand name or incoming host never grants access.
        theme = site.get('portal_theme', 'fortifyhp' if site_id == 'fortifyhp' else 'default')
        if theme not in ('default', 'fortifyhp'):
            theme = 'default'
        return site, {'id': site_id, 'name': site['name'], 'color': brand.get('color', '#245844'),
                      'logo_url': brand.get('logo_url') or ('/portal-assets/fortifyhp/logo.png' if theme == 'fortifyhp' else ''), 'support_email': brand.get('support_email', ''),
                      'theme': theme}

    def origin(self, req):
        site_id = getattr(req, 'path_params', {}).get('site_id')
        if req.headers.get('origin') not in (None, *self.portal_origins(site_id)):
            raise HTTPException(403, 'Use this site’s registered portal origin')

    def portal_origins(self, site_id):
        site = self.admin.get('site', site_id or '') or {}
        origins = site.get('portal_origins', [])
        # This deployed storefront is explicitly owned by the FortifyHP client.
        # Additional clients register exact HTTPS origins in their site record.
        if site_id == 'fortifyhp' and site:
            origins = [*origins, 'https://fortifyhp-care.lovable.app']
        return [self.cfg.public_url, *[o for o in origins if isinstance(o, str)
            and re.fullmatch(r'https://[A-Za-z0-9.-]+(?::[0-9]+)?', o)]]

    def patient(self, site_id, req, credentials):
        self.site(site_id)
        self.origin(req)
        if not credentials or len(credentials.credentials) > 200:
            raise HTTPException(401, 'Sign in to this site’s patient portal')
        with self.db() as db:
            row = db.execute('SELECT p.* FROM member_sessions s JOIN member_patients p ON p.id=s.patient_id AND p.site_id=s.site_id WHERE s.token_hash=? AND s.site_id=? AND s.expires>?',
                             (digest(credentials.credentials), site_id, self.clock())).fetchone()
        if not row:
            raise HTTPException(401, 'Your portal session expired. Please sign in again.')
        if self.identity:
            self.identity.check_session(digest(credentials.credentials))
        return dict(row)

    def patient_public(self, patient):
        return {key: patient[key] for key in ('id', 'name', 'email')}

    def session(self, patient, member=None):
        token = secrets.token_urlsafe(32)
        expires = self.clock() + SESSION_SECONDS
        with self.db() as db:
            db.execute('DELETE FROM member_sessions WHERE expires<=?', (self.clock(),))
            db.execute('INSERT INTO member_sessions VALUES(?,?,?,?)', (digest(token), patient['site_id'], patient['id'], expires))
        if self.identity:
            if member is None:
                raise HTTPException(401, 'Please sign in with your Sticky member password.')
            expires = min(expires, self.identity.save_session(digest(token), member))
        return {'access_token': token, 'expires_at': stamp(expires), 'patient': self.patient_public(patient), 'site': self.site(patient['site_id'])[1]}

    def captured(self, site_id, order_id=None):
        site, _ = self.site(site_id)
        query = "SELECT * FROM checkouts WHERE status='captured' AND order_id IS NOT NULL"
        parameters = []
        if order_id:
            query += ' AND order_id=?'
            parameters.append(str(order_id))
        with self.db() as db:
            rows = db.execute(query, parameters).fetchall()
        results = []
        for row in rows:
            row = dict(row)
            link = self.admin.get('link', row.get('link_id') or '') or {}
            plan = self.admin.get('plan_checkout', link.get('plan_checkout_id') or '') or {}
            # No campaign-only or email inference: the published plan owns its site.
            if (plan.get('site_id') != site_id or link.get('brand_id') != site['brand_id']
                    or plan.get('brand_id') != site['brand_id'] or row['campaign'] != site['campaign_id']
                    or plan.get('campaign_id') != site['campaign_id'] or link.get('sku') != row['sku']):
                continue
            row['_plan'] = plan
            results.append(row)
        return results

    def sync(self, site_id, order_id, allow_historical=False, allow_import=False, follow_children=True):
        if not re.fullmatch(r'\d{1,40}', str(order_id)):
            raise HTTPException(422, 'Use a valid Sticky order ID')
        site, _ = self.site(site_id)
        candidates = self.captured(site_id, order_id)
        with self.db() as db:
            any_binding = db.execute('SELECT * FROM member_orders WHERE order_id=?', (str(order_id),)).fetchone()
        if any_binding and any_binding['site_id'] != site_id:
            raise HTTPException(409, 'This order already belongs to another site')
        old = dict(any_binding) if any_binding else None
        historical = None
        if not candidates and not old and allow_historical:
            with self.db() as db:
                rows = db.execute("SELECT * FROM checkouts WHERE status='captured' AND order_id=? AND campaign=? AND link_id IS NULL", (str(order_id), site['campaign_id'])).fetchall()
            if len(rows) == 1:
                historical = dict(rows[0])
        if not candidates and not old and not historical and not allow_import:
            raise HTTPException(404, 'No captured checkout attributable to this site was found for that order')
        attempt = candidates[0] if candidates else historical
        try:
            remote = self.provider.read_order(str(order_id), expected_campaign=site['campaign_id'],
                                              expected_customer_id=old['customer_id'] if old else None)
        except ProviderError:
            raise HTTPException(502, 'Sticky order details could not be verified. Saved records have been preserved.') from None
        if str(remote.get('campaign_id')) != str(site['campaign_id']) or not remote.get('customer_id'):
            raise HTTPException(409, 'Sticky returned an order outside this site’s verified ownership')
        products = remote.get('products', [])
        if len(products) != 1:
            raise HTTPException(409, 'Multi-product orders need an explicit product-level ownership mapping before import')
        product = products[0]
        quote = json.loads(attempt['quote'] or '{}') if attempt else {}
        if old:
            snapshot = json.loads(old['snapshot'])
            expected_product, expected_sku = snapshot['product_id'], old['sku']
            therapy_id, attempt_id = old['therapy_id'], old['attempt_id']
        else:
            if attempt:
                expected_product = str(quote.get('option', {}).get('productId') or (self.cfg.product_id if attempt['id'] == 'legacy' and attempt['sku'] == self.cfg.sku else ''))
                expected_sku = attempt['sku']
                plan = attempt.get('_plan') or {}
                attempt_id = attempt['id']
            else:
                # Explicit owner import of a Sticky order is limited to this
                # site's campaign AND its managed, exact product/SKU assignment.
                matched = [o for o in self.admin.records('offering') if o.get('brand_id') == site['brand_id']
                           and str(o.get('campaign_id')) == str(site['campaign_id'])
                           and str(o.get('product_id')) == str(product.get('product_id')) and o.get('sku') == product.get('sku')]
                if not matched:
                    raise HTTPException(409, 'The Sticky order product is not assigned to this site')
                expected_product, expected_sku = str(product['product_id']), product['sku']
                plans = [p for p in self.admin.records('plan_checkout') if p.get('site_id') == site_id
                         and any(e.get('sku') == expected_sku for e in p.get('entries', []))]
                plan = plans[0] if len(plans) == 1 else {}
                attempt_id = ''
            masters = (plan.get('template_snapshot') or {}).get('masters', [])
            master = next((m for m in masters if m.get('sku') == expected_sku), None) or self.admin.get('master', expected_sku) or {}
            therapy_id = plan.get('therapy_id') or master.get('therapy_id') or ''
            snapshot = {'therapy_id': therapy_id, 'therapy_name': (self.admin.get('therapy', therapy_id) or {}).get('name', therapy_id),
                        'product_id': expected_product, 'product_setup': master.get('product_setup') or {},
                        'planning_contract': master.get('planning_contract') or {}, 'product_name': master.get('name') or product.get('name') or expected_sku,
                        'payment_test_only': bool(plan.get('payment_test_only')), 'quote_option': quote.get('option') or {},
                        'root_order_id': str(order_id), 'term_order_id': str(order_id), 'term_started_at': remote.get('created_at'),
                        'term_upfront_total': str(remote['total']),
                        'source': 'checkout' if attempt else 'owner_import', 'schedule_verified': bool(attempt and quote.get('option'))}
        if str(product.get('product_id')) != str(expected_product) or product.get('sku') != expected_sku:
            raise HTTPException(409, 'The order product does not match its verified site assignment')
        if remote.get('currency') is None:
            remote['currency'] = quote.get('currency') or (json.loads(old['payload']).get('currency') if old else None)
        self.save_order(site_id, str(order_id), str(remote['customer_id']), attempt_id, therapy_id, expected_sku, snapshot, remote)
        row = self.order_record(site_id, str(order_id))
        if follow_children:
            self.sync_children(row)
        return row

    def save_order(self, site_id, order_id, customer_id, attempt_id, therapy_id, sku, snapshot, remote):
        with self.db() as db:
            existing = db.execute('SELECT site_id,customer_id FROM member_orders WHERE order_id=?', (order_id,)).fetchone()
            if existing and (existing['site_id'] != site_id or existing['customer_id'] != customer_id):
                raise HTTPException(409, 'This order already has a different site or patient identity')
            db.execute('INSERT INTO member_orders VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(site_id,order_id) DO UPDATE SET payload=excluded.payload,synced=excluded.synced',
                       (site_id, order_id, customer_id, attempt_id, therapy_id, sku, encoded(snapshot), encoded(remote), self.clock()))

    def sync_children(self, parent):
        """Follow at most twenty explicitly linked orders; never search by email."""
        queue = [parent]
        seen = {parent['order_id']}
        count = 0
        fetched = {}
        while queue:
            current = queue.pop(0)
            original, snapshot = json.loads(current['payload']), json.loads(current['snapshot'])
            for child_id in original.get('child_ids', []):
                child_id = str(child_id)
                if child_id in seen:
                    continue
                if child_id not in fetched:
                    if count >= 20:
                        continue
                    count += 1
                    try:
                        fetched[child_id] = self.provider.read_order(child_id, expected_campaign=original['campaign_id'], expected_customer_id=current['customer_id'])
                    except ProviderError:
                        fetched[child_id] = None
                child = fetched[child_id]
                if not child or str(child.get('parent_id')) != current['order_id']:
                    # Ancestors list every descendant. Establish each paid term
                    # from its direct predecessor, never the initial ancestor.
                    continue
                seen.add(child_id)
                related = (str(child.get('parent_id')) == current['order_id'] or str(child.get('ancestor_id')) == str(snapshot['root_order_id']))
                lines = child.get('products', [])
                root_line = original['products'][0]
                if (not related or len(lines) != 1 or str(lines[0].get('product_id')) != str(snapshot['product_id'])
                        or lines[0].get('sku') != current['sku'] or not root_line.get('subscription_id')
                        or lines[0].get('subscription_id') != root_line['subscription_id']):
                    continue
                child_snapshot = dict(snapshot)
                prepaid, previous_prepaid = lines[0].get('prepaid'), root_line.get('prepaid')
                renewed_term = (child.get('payment_status') == 'paid' and Decimal(str(child['total'])) > 0 and
                                ((not prepaid and not previous_prepaid and lines[0].get('is_recurring') is True)
                                 or (prepaid and previous_prepaid and prepaid.get('current_cycle') == 1
                                     and previous_prepaid.get('current_cycle') == previous_prepaid.get('total_cycles')
                                     and previous_prepaid.get('renews') is True
                                     and Decimal(str(child['total'])) == Decimal(str(snapshot.get('term_upfront_total', '-1'))))))
                if renewed_term:
                    child_snapshot.update(term_order_id=child_id, term_started_at=child.get('created_at'), term_upfront_total=str(child['total']))
                self.save_order(current['site_id'], child_id, current['customer_id'], current['attempt_id'], current['therapy_id'], current['sku'], child_snapshot, child)
                with self.db() as db:
                    grant = db.execute('SELECT * FROM member_grants WHERE site_id=? AND order_id=?', (current['site_id'], current['order_id'])).fetchone()
                    if grant:
                        existing = db.execute('SELECT patient_id FROM member_grants WHERE site_id=? AND order_id=?', (current['site_id'], child_id)).fetchone()
                        if existing and existing['patient_id'] != grant['patient_id']:
                            raise HTTPException(409, 'A renewal order has a different patient assignment')
                        db.execute('INSERT OR IGNORE INTO member_grants VALUES(?,?,?,?,?)', (current['site_id'], child_id, grant['patient_id'], self.clock(), 'verified_subscription_child'))
                queue.append(self.order_record(current['site_id'], child_id))
        return {'inspected': count, 'more_available': bool(queue)}

    def issue_invite(self, site_id, order):
        with self.db() as db:
            granted = db.execute('SELECT 1 FROM member_grants WHERE site_id=? AND order_id=?', (site_id, order['order_id'])).fetchone()
            if granted:
                return {'site_id': site_id, 'enrollment_url': self.cfg.public_url + '/portal/' + site_id, 'expires_at': None}
            token, now = secrets.token_urlsafe(32), self.clock()
            db.execute('DELETE FROM member_invites WHERE site_id=? AND order_id=? AND used IS NULL', (site_id, order['order_id']))
            db.execute('INSERT INTO member_invites VALUES(?,?,?,?,?,?,NULL)', (digest(token), site_id, order['order_id'], order['customer_id'], now, now + INVITE_SECONDS))
        return {'site_id': site_id, 'enrollment_url': self.cfg.public_url + '/portal/' + site_id + '#invite=' + token, 'expires_at': stamp(now + INVITE_SECONDS)}

    def receipt_invite(self, row):
        if not row or row.get('status') != 'captured' or not row.get('order_id'):
            raise HTTPException(409, 'Complete this checkout before opening the patient portal')
        link = self.admin.get('link', row.get('link_id') or '') or {}
        plan = self.admin.get('plan_checkout', link.get('plan_checkout_id') or '') or {}
        site_id = plan.get('site_id')
        if not site_id or not any(c['id'] == row['id'] for c in self.captured(site_id, str(row['order_id']))):
            raise HTTPException(409, 'This receipt needs a site assignment before portal enrollment')
        order = self.sync(site_id, str(row['order_id']))
        return self.issue_invite(site_id, order)

    def order_record(self, site_id, order_id, patient=None):
        with self.db() as db:
            if patient:
                row = db.execute('SELECT o.* FROM member_orders o JOIN member_grants g ON g.site_id=o.site_id AND g.order_id=o.order_id WHERE o.site_id=? AND o.order_id=? AND g.patient_id=?',
                                 (site_id, order_id, patient['id'])).fetchone()
            else:
                row = db.execute('SELECT * FROM member_orders WHERE site_id=? AND order_id=?', (site_id, order_id)).fetchone()
        if not row:
            raise HTTPException(404, 'Order not found in this account')
        return dict(row)

    def care_order_role(self, row):
        from .order_roles import order_role
        root_id = str(json.loads(row['snapshot']).get('root_order_id') or row['order_id'])
        with self.db() as db:
            root = db.execute('SELECT * FROM member_orders WHERE site_id=? AND order_id=?', (row['site_id'], root_id)).fetchone()
        return order_role(row, dict(root) if root else None)

    def rule(self, sku, site_id=None):
        if site_id:
            saved = self.admin.get('site_refill_policy', site_rule_key(site_id, sku))
            if saved and saved.get('site_id') == site_id and saved.get('sku') == sku:
                return saved
        return self.admin.get('refill_policy', sku) or {'enabled': False, 'minimum_days': 0, 'request_window_days': 14,
                                                     'check_in_required': True, 'review_required': True, 'test_requests_enabled': False, 'revision': 0}

    def site_rule_products(self, site_id):
        site, _ = self.site(site_id)
        products = {}
        for plan in self.admin.records('plan_checkout'):
            if (plan.get('site_id') != site_id or plan.get('brand_id') != site['brand_id']
                    or plan.get('campaign_id') != site['campaign_id']):
                continue
            for master in (plan.get('template_snapshot') or {}).get('masters', []):
                if master.get('sku'):
                    products[master['sku']] = master
        return products

    def site_rule_public(self, site_id, sku, product):
        saved = self.admin.get('site_refill_policy', site_rule_key(site_id, sku))
        rule = self.rule(sku, site_id)
        result = RefillRules.model_validate({key: value for key, value in rule.items() if key in RefillRules.model_fields}).model_dump()
        return dict(result, sku=sku, site_id=site_id, name=product.get('name') or sku,
                    revision=saved['revision'] if saved else 0, source='site' if saved else 'master')

    @staticmethod
    def date(value):
        if not value:
            return None
        for fmt in (None, '%m/%d/%Y %H:%M:%S', '%m/%d/%Y', '%Y-%m-%d %H:%M:%S'):
            try:
                return (datetime.fromisoformat(str(value).replace('Z', '+00:00')) if fmt is None else datetime.strptime(str(value), fmt)).date()
            except ValueError:
                pass
        return None

    def refill_availability(self, row, task_id=None):
        if self.care.configured(row):
            return self.care.availability(row, task_id)
        if task_id is not None:
            raise HTTPException(404, 'This order does not have that care checkpoint')
        return self.legacy_refill_availability(row)

    def legacy_refill_availability(self, row):
        raw, snapshot, rule = json.loads(row['payload']), json.loads(row['snapshot']), self.rule(row['sku'], row['site_id'])
        line = raw['products'][0]
        test_only = bool(snapshot.get('payment_test_only') or raw.get('test_order'))
        result = {'eligible': False, 'reason': 'Refill requests are not enabled for this SKU.', 'next_date': None, 'test_only': test_only}
        if not rule.get('enabled'):
            return result
        if line.get('subscription_id'):
            with self.db() as db:
                related_orders = db.execute('SELECT * FROM member_orders WHERE site_id=? AND customer_id=? AND sku=?', (row['site_id'], row['customer_id'], row['sku'])).fetchall()
            for other in related_orders:
                if other['order_id'] == row['order_id']:
                    continue
                other_raw, other_snapshot = json.loads(other['payload']), json.loads(other['snapshot'])
                other_line = other_raw['products'][0]
                if (other_snapshot.get('root_order_id') == snapshot.get('root_order_id')
                        and other_line.get('subscription_id') == line['subscription_id']
                        and int(other['order_id']) > int(row['order_id'])):
                    return result | {'reason': 'Use the latest verified order in this subscription for a refill review.'}
        if test_only and not rule.get('test_requests_enabled'):
            return result | {'reason': 'This payment-test product does not provide medication refills.'}
        shippable = line.get('is_shippable')
        if not shippable and not (test_only and rule.get('test_requests_enabled')):
            return result | {'reason': 'This product does not have a verified medication delivery entitlement.'}
        if raw.get('payment_status') not in ('approved', 'paid', 'captured'):
            return result | {'reason': 'The current payment status must be confirmed before a refill request.'}
        original = snapshot.get('quote_option') or {}
        renewal = original.get('renewal', original.get('recurring', False))
        if line.get('billing_status') == 'held' or line.get('on_hold') is True or ((renewal or line.get('is_recurring')) and line.get('billing_status') != 'active'):
            return result | {'reason': 'Refill access requires an active billing entitlement.'}
        created = self.date(snapshot.get('term_started_at') or raw.get('created_at'))
        if created is None:
            return result | {'reason': 'The order date needs verification before scheduling a refill.'}
        minimum_days = int(rule.get('minimum_days', 0))
        setup = snapshot.get('product_setup', {})
        cycle = 1
        if setup.get('shipment_count') and setup.get('shipment_interval_days'):
            if not snapshot.get('schedule_verified'):
                return result | {'reason': 'This imported order’s original shipment schedule needs verification before refill requests.'}
            prepaid = line.get('prepaid') or {}
            cycle = int(prepaid.get('current_cycle') or 1)
            if cycle >= int(setup['shipment_count']):
                return result | {'reason': 'All included shipments for this term have been scheduled.'}
            days = max(minimum_days, cycle * int(setup['shipment_interval_days']))
        else:
            days = minimum_days
        due = created + timedelta(days=days)
        today = datetime.fromtimestamp(self.clock(), timezone.utc).date()
        result['next_date'] = due.isoformat()
        result['_cycle_key'] = f'{snapshot.get("root_order_id", row["order_id"])}:{line.get("subscription_id") or line["product_id"]}:{snapshot.get("term_order_id", row["order_id"])}:{cycle}:{due.isoformat()}'
        early_date = created + timedelta(days=int(rule.get('early_request_minimum_days', 0)))
        with self.db() as db:
            last_early = self.care.last_early(db, row, self.care.grant(row))
        if last_early is not None:
            early_date = max(early_date, datetime.fromtimestamp(last_early, timezone.utc).date() + timedelta(days=int(rule.get('early_request_cooldown_days', 7))))
        result['early_next_date'] = early_date.isoformat()
        result['early_allowed'] = bool(rule.get('allow_early_requests')) and today >= early_date and (last_early is None or self.clock() >= last_early + int(rule.get('early_request_cooldown_days', 7)) * 86400)
        result['early_reason'] = 'Request an early refill review. No schedule, charge or shipment changes automatically.' if result['early_allowed'] else 'Early refill requests are not enabled or their waiting period has not ended.'
        opening_date = max(created + timedelta(days=minimum_days), due - timedelta(days=int(rule.get('request_window_days', 14))))
        if today < opening_date:
            return result | {'reason': 'Your next refill request window has not opened yet.'}
        extra_purchase = not renewal and not line.get('prepaid')
        result['additional_purchase_may_be_required'] = extra_purchase
        reason = 'Request a refill review. This does not create a shipment or charge.'
        if extra_purchase:
            reason += ' An additional purchase may be required; this does not claim another included shipment.'
        return result | {'eligible': True, 'reason': reason}

    def order_public(self, row):
        raw, snapshot = json.loads(row['payload']), json.loads(row['snapshot'])
        line = raw['products'][0]
        with self.db() as db:
            intake = db.execute('SELECT status FROM member_intakes WHERE site_id=? AND order_id=?', (row['site_id'], row['order_id'])).fetchone()
        subscriptions = []
        # Sticky assigns internal subscription IDs to one-time sales too.
        # Preserve real active/held and prepaid cycles, but do not present a
        # verified single purchase as an inactive monthly subscription.
        purchased = snapshot.get('quote_option') or {}
        single_purchase = (not line.get('prepaid') and line.get('is_recurring') is False
            and line.get('billing_status') == 'inactive'
            and (purchased.get('recurring') is False or str(line.get('billing_model_id')) == '2'))
        if line.get('subscription_id') and not single_purchase:
            actions = ['pause'] if line.get('billing_status') == 'active' else ['resume'] if line.get('billing_status') == 'held' else []
            subscriptions.append({'id': str(line['subscription_id']), 'product_id': str(line['product_id']), 'status': line.get('billing_status', 'unknown'),
                                  'next_billing_date': line.get('next_billing_date'), 'next_cycle_date': line.get('next_cycle_date'), 'billing_interval_days': line.get('billing_interval_days'), 'actions': actions,
                                  'prepaid_renews': (line.get('prepaid') or {}).get('renews'),
                                  'address_update_available': bool(raw.get('contact_id')) and line.get('billing_status') in ('active', 'held'),
                                  'shipping_address': line.get('subscription_shipping_address')})
        availability = self.refill_availability(row)
        availability = {key: value for key, value in availability.items() if not key.startswith('_')}
        care_plan = self.care.public(row)
        if care_plan and care_plan['tasks']:
            intake = {'status': care_plan['tasks'][0]['intake_status']}
        role = self.care_order_role(row)
        intake_kind = 'initial' if role == 'initial' else 'checkin'
        if role == 'included_refill' and care_plan:
            own_task = next((t for t in care_plan['tasks'] if str((t.get('claim') or {}).get('order_id')) == row['order_id']), None)
            intake = {'status': own_task['intake_status'] if own_task else 'not_started'}
        if role == 'paid_renewal' and not care_plan and not self.rule(row['sku'], row['site_id']).get('check_in_required', True):
            intake = intake or {'status': 'not_required'}
        if intake and intake['status'] == 'not_required':
            intake_kind = 'none'
        dry_run = raw.get('test_order') is True and str(raw.get('gateway_id')) == '1'
        result = {'order_role': role, 'intake_kind': intake_kind, 'dry_run': dry_run, 'care_plan': care_plan, 'id': row['order_id'], 'number': row['order_id'], 'site_id': row['site_id'], 'therapy_id': row['therapy_id'],
                'therapy_name': snapshot.get('therapy_name', row['therapy_id']), 'product_name': snapshot.get('product_name', row['sku']),
                'sku': row['sku'], 'plan_name': snapshot.get('quote_option', {}).get('label') or row['sku'], 'total': str(raw['total']),
                'currency': raw.get('currency'), 'payment_status': raw.get('payment_status', 'unknown'), 'intake_status': intake['status'] if intake else 'not_started',
                'medical_status': 'not_connected', 'fulfillment_status': raw.get('fulfillment_status', 'unknown'), 'created_at': raw.get('created_at'),
                'tracking_number': raw.get('tracking_number'), 'shipping_date': raw.get('shipping_date'),
                'last_synced_at': stamp(row['synced']), 'subscriptions': subscriptions, 'refill': availability, 'test_only': availability['test_only'],
                'address_update_available': raw.get('fulfillment_posted') is not None and raw.get('fulfillment_posted') == 0 and raw.get('fulfillment_status') not in ('shipped', 'not_shippable') and not raw.get('child_ids') and not raw.get('shipping_date') and not raw.get('tracking_number'),
                'shipping_address': raw.get('shipping_address')}
        from .journey import order_journey
        result['journey'] = order_journey(result)
        return result

    def order_list(self, site_id, patient=None, therapy_id=None):
        with self.db() as db:
            if patient:
                rows = db.execute('SELECT o.* FROM member_orders o JOIN member_grants g ON g.site_id=o.site_id AND g.order_id=o.order_id WHERE o.site_id=? AND g.patient_id=? ORDER BY o.synced DESC', (site_id, patient['id'])).fetchall()
            else:
                rows = db.execute('SELECT * FROM member_orders WHERE site_id=? ORDER BY synced DESC', (site_id,)).fetchall()
        return [self.order_public(dict(row)) for row in rows if not therapy_id or row['therapy_id'] == therapy_id]

    def enroll(self, site_id, order, password, source, invite_token=None):
        raw = json.loads(order['payload'])
        contact = raw['customer']
        email = contact['email'].strip().lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            raise HTTPException(409, 'The order email needs review before account creation')
        if self.identity:
            return self.enroll_sticky(site_id, order, email, password, source, invite_token)
        salt = secrets.token_hex(16)
        password_value = password_hash(password, salt)
        patient_id = identifier('patient')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if invite_token:
                invite = db.execute('SELECT * FROM member_invites WHERE token_hash=? AND site_id=? AND order_id=?',
                                    (digest(invite_token), site_id, order['order_id'])).fetchone()
                if not invite or invite['used'] is not None or invite['expires'] <= self.clock():
                    raise HTTPException(410, 'This enrollment invitation expired or was already used')
            if db.execute('SELECT 1 FROM member_grants WHERE site_id=? AND order_id=?', (site_id, order['order_id'])).fetchone():
                raise HTTPException(409, 'This order is already connected to a patient account. Please sign in.')
            if db.execute('SELECT 1 FROM member_patients WHERE site_id=? AND (email=? OR customer_id=?)', (site_id, email, order['customer_id'])).fetchone():
                raise HTTPException(409, 'A patient account already exists for this order. Sign in to connect it.')
            db.execute('INSERT INTO member_patients VALUES(?,?,?,?,?,?,?,?,?)', (patient_id, site_id, order['customer_id'], contact.get('name') or 'Patient', email, salt, password_value, source, self.clock()))
            db.execute('INSERT INTO member_grants VALUES(?,?,?,?,?)', (site_id, order['order_id'], patient_id, self.clock(), source))
            if invite_token:
                db.execute('UPDATE member_invites SET used=? WHERE token_hash=?', (self.clock(), digest(invite_token)))
            patient = dict(db.execute('SELECT * FROM member_patients WHERE id=?', (patient_id,)).fetchone())
        self.adopt_receipt_intake(order, patient)
        self.sync_children(order)
        return self.session(patient)

    def enroll_sticky(self, site_id, order, email, password, source, invite_token):
        with self.identity.lock_for(email):
            with self.db() as db:
                if invite_token:
                    invite = db.execute('SELECT * FROM member_invites WHERE token_hash=? AND site_id=? AND order_id=? AND expires>?',
                        (digest(invite_token), site_id, order['order_id'], self.clock())).fetchone()
                    if not invite or invite['used'] is not None:
                        raise HTTPException(410, 'This enrollment invitation expired or was already used')
            state = self.identity.setup_state(email, site_id, order['order_id'])
            if state == 'sign_in':
                member = self.authenticate_password(site_id, email, password)
            else:
                member = self.identity.setup(email, password, site_id, order['order_id'], order['customer_id'])
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                patient = db.execute('SELECT * FROM member_patients WHERE site_id=? AND email=?', (site_id, email)).fetchone()
                if not patient:
                    if db.execute('SELECT 1 FROM member_patients WHERE site_id=? AND customer_id=?', (site_id, order['customer_id'])).fetchone():
                        raise HTTPException(409, 'This order identity needs review before linking an account.')
                    patient_id = identifier('patient')
                    contact = json.loads(order['payload'])['customer']
                    db.execute('INSERT INTO member_patients VALUES(?,?,?,?,?,?,?,?,?)',
                        (patient_id, site_id, order['customer_id'], contact.get('name') or 'Patient', email, '', '', 'sticky', self.clock()))
                else:
                    patient_id = patient['id']
                grant = db.execute('SELECT patient_id FROM member_grants WHERE site_id=? AND order_id=?', (site_id, order['order_id'])).fetchone()
                if grant and grant['patient_id'] != patient_id:
                    raise HTTPException(409, 'This order belongs to a different patient account.')
                db.execute('UPDATE member_patients SET salt=?,password_hash=?,identity_source=? WHERE id=?', ('', '', 'sticky', patient_id))
                db.execute('INSERT OR IGNORE INTO member_grants VALUES(?,?,?,?,?)', (site_id, order['order_id'], patient_id, self.clock(), source))
                if invite_token:
                    db.execute('UPDATE member_invites SET used=? WHERE token_hash=?', (self.clock(), digest(invite_token)))
                patient = dict(db.execute('SELECT * FROM member_patients WHERE id=?', (patient_id,)).fetchone())
            self.adopt_receipt_intake(order, patient)
            self.sync_children(order)
            return self.session(patient, member)

    def adopt_receipt_intake(self, order, patient):
        guest = 'receipt:' + order['order_id']
        if patient['id'] == guest:
            return
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            # The caller has proved this exact order grant. Never merge by email.
            granted = db.execute('SELECT 1 FROM member_grants WHERE site_id=? AND order_id=? AND patient_id=?',
                (order['site_id'], order['order_id'], patient['id'])).fetchone()
            existing = db.execute('SELECT 1 FROM member_intakes WHERE site_id=? AND order_id=? AND patient_id=?',
                (order['site_id'], order['order_id'], patient['id'])).fetchone()
            if granted and not existing:
                db.execute('UPDATE member_intakes SET patient_id=? WHERE site_id=? AND order_id=? AND patient_id=?',
                    (patient['id'], order['site_id'], order['order_id'], guest))

        if patient.get('_reuse_allowed') is not False:
            self.identity_checks.status(order, patient)
            self.id_uploads.status(order, patient)

    def care_task_for_order(self, order):
        if self.care_order_role(order) != 'included_refill':
            return 'initial'
        tasks = self.care.public(order)['tasks']
        task = next((t for t in tasks if str((t.get('claim') or {}).get('order_id')) == str(order['order_id'])), None)
        if not task:
            raise HTTPException(409, 'This refill order needs its claim to be confirmed before its check-in')
        return task['id']

    def initial_intake(self, order, patient):
        self.adopt_receipt_intake(order, patient)
        if self.care.configured(order) and self.care.ensure(order):
            _, _, record = self.care.intake(order, patient, self.care_task_for_order(order))
            return self.care.intake_public(order, record)
        return self.intake_public(self.intake(order, patient), order)

    def receipt_order(self, row):
        if not row or row.get('status') != 'captured' or not row.get('order_id'):
            raise HTTPException(409, 'Complete this checkout before opening its intake')
        link = self.admin.get('link', row.get('link_id') or '') or {}
        plan = self.admin.get('plan_checkout', link.get('plan_checkout_id') or '') or {}
        site_id = plan.get('site_id')
        if not site_id or not any(c['id'] == row['id'] for c in self.captured(site_id, str(row['order_id']))):
            raise HTTPException(403, 'This receipt does not belong to a verified site order')
        try:
            order = self.order_record(site_id, str(row['order_id']))
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            order = self.sync(site_id, str(row['order_id']))
        with self.db() as db:
            grant = db.execute('SELECT patient_id FROM member_grants WHERE site_id=? AND order_id=?', (site_id, order['order_id'])).fetchone()
        return order, {'id': grant['patient_id'] if grant else 'receipt:' + order['order_id'], '_reuse_allowed': False}

    def receipt_journey(self, row, refresh=False):
        order, _ = self.receipt_order(row)
        if refresh and self.clock() - order['synced'] >= 30:
            order = self.sync(order['site_id'], order['order_id'])
        public = self.order_public(order)
        # Receipt capability reveals only this purchase, never account-wide
        # health answers, identity records or another product's order history.
        return {key: public[key] for key in ('id', 'product_name', 'intake_status', 'journey')}

    def modify_initial(self, order, body, patient, submit=False):
        if submit:
            self.identity_checks.require(order, patient)
        site_id, order_id = order["site_id"], order["order_id"]
        self.adopt_receipt_intake(order, patient)
        if self.care.configured(order) and self.care.ensure(order):
            return self.care.modify(order, patient, self.care_task_for_order(order), body, submit)
        self.intake(order, patient)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = dict(db.execute('SELECT * FROM member_intakes WHERE site_id=? AND order_id=? AND patient_id=?', (site_id, order_id, patient['id'])).fetchone())
            if row['status'] == 'submitted' or row['revision'] != body.revision:
                raise HTTPException(409, 'This intake is submitted or changed. Reload before saving.')
            template, answers = json.loads(row['template']), json.loads(row['answers'])
            now = self.clock()
            self.answer_profile.validate(db, order, patient, template, incoming=None if submit else body.answers, submit=submit, answers=answers)
            if submit:
                questions = [q for q in template['questions'] if visible(q, answers)]
                missing = [q['id'] for q in questions if q.get('required') and answers.get(q['id']) in (None, '', [])]
                if missing:
                    raise HTTPException(422, {'code': 'required_answers_missing', 'question_ids': missing})
                answers = {q['id']: answers[q['id']] for q in questions if q['id'] in answers}
                db.execute("UPDATE member_intakes SET status='submitted',revision=revision+1,answers=?,submitted_answers=?,updated=?,submitted=? WHERE id=?", (encoded(answers), encoded(answers), now, now, row['id']))
            else:
                for key, value in clean_answers(template, body.answers).items():
                    if value is None:
                        answers.pop(key, None)
                    else:
                        answers[key] = value
                step = row['current_step'] if body.current_step is None else body.current_step
                if not 0 <= step < len(template['sections']):
                    raise HTTPException(422, 'Unknown intake step')
                db.execute('UPDATE member_intakes SET answers=?,current_step=?,revision=revision+1,updated=? WHERE id=?', (encoded(answers), step, now, row['id']))
            row = dict(db.execute('SELECT * FROM member_intakes WHERE id=?', (row['id'],)).fetchone())
        return self.intake_public(row, order)

    def intake(self, order, patient):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM member_intakes WHERE site_id=? AND order_id=? AND patient_id=?', (order['site_id'], order['order_id'], patient['id'])).fetchone()
            if row:
                return self.answer_profile.hydrate(db, order, patient, row, 'member_intakes')
            therapy = order['therapy_id']
            from .intake_templates import get_template as sku_template, binding_for_sku
            binding = binding_for_sku(order['sku'])
            if therapy not in QUESTION_THERAPIES and (not binding or binding['template_id'] != therapy):
                raise HTTPException(409, 'This therapy’s intake questions have not been configured yet')
            role = self.care_order_role(order)
            if role == 'unconfirmed' or role == 'included_refill':
                raise HTTPException(409, 'The refill order needs a verified care checkpoint')
            if role == 'paid_renewal' and not self.rule(order['sku'], order['site_id']).get('check_in_required', True):
                raise HTTPException(409, 'This refill does not require a check-in')
            if role == 'paid_renewal' and not binding:
                raise HTTPException(409, 'This product needs a configured refill check-in')
            template = sku_template(therapy, sku=order['sku'], kind='checkin' if role == 'paid_renewal' else 'initial') if binding else get_template(therapy)
            template['questions'] = [q for q in template['questions'] if q['id'] != 'demo_confirmation']
            template, answers = self.answer_profile.seed(db, order, patient, template)
            db.execute('INSERT INTO member_intakes VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (identifier('intake'), order['site_id'], order['order_id'], patient['id'], 'draft', 0, encoded(answers), 0, encoded(template), self.clock(), None, None))
            return dict(db.execute('SELECT * FROM member_intakes WHERE site_id=? AND order_id=? AND patient_id=?', (order['site_id'], order['order_id'], patient['id'])).fetchone())

    def intake_public(self, row, order):
        return {'id': row['id'], 'order_id': row['order_id'], 'therapy_id': order['therapy_id'], 'status': row['status'], 'revision': row['revision'],
                'answers': json.loads(row['answers']), 'current_step': row['current_step'], 'updated_at': stamp(row['updated']),
                'submitted_at': stamp(row['submitted']) if row['submitted'] is not None else None, 'template': json.loads(row['template']),
                'reused_fields': [q['id'] for q in json.loads(row['template'])['questions'] if q.get('reuse_status') in ('stable', 'verified')], 'provider_connected': False}

    def messages(self, site_id, patient_id):
        with self.db() as db:
            rows = db.execute('SELECT * FROM member_messages WHERE site_id=? AND patient_id=? ORDER BY created,rowid', (site_id, patient_id)).fetchall()
        return [{'id': r['id'], 'sender': r['sender'], 'body': r['body'], 'created_at': stamp(r['created']), 'client_message_id': r['client_message_id'], 'automated': r['sender'] == 'system'} for r in rows]

    def message_draft(self, site_id, patient_id):
        with self.db() as db:
            row = db.execute('SELECT * FROM member_message_drafts WHERE site_id=? AND patient_id=?', (site_id, patient_id)).fetchone()
        return {'body': row['body'] if row else '', 'revision': row['revision'] if row else 0,
                'updated_at': stamp(row['updated']) if row else None, 'provider_connected': False}

    def notifications(self, site_id, patient):
        items = order_notifications(self.order_list(site_id, patient), site_id, patient['id'])
        with self.db() as db:
            reads = {r['notification_id']: stamp(r['created']) for r in db.execute(
                'SELECT notification_id,created FROM member_notification_reads WHERE site_id=? AND patient_id=?', (site_id, patient['id']))}
        for item in items:
            item['read_at'] = reads.get(item['id'])
        items.sort(key=lambda item: (bool(item['read_at']), item['kind'] in ('shipped', 'delivered')))
        return {'notifications': items, 'unread_count': sum(item['read_at'] is None for item in items)}

    def store_catalog(self, site_id, therapy_id=None):
        site, public_site = self.site(site_id)
        published = [plan for plan in self.admin.records('plan_checkout') if plan.get('site_id') == site_id
            and plan.get('brand_id') == site['brand_id'] and str(plan.get('campaign_id')) == str(site['campaign_id'])
            and plan.get('enabled') and plan.get('visibility') == 'public'
            and (not therapy_id or plan.get('therapy_id') == therapy_id)]
        # Local configuration changes invalidate the short read cache. Every
        # purchase still goes through the existing checkout's fresh quote.
        config = {kind: self.admin.records(kind) for kind in ('link', 'master', 'purchase_option', 'therapy', 'brand', 'offering')}
        key = digest(encoded({'site': site, 'plans': published, 'config': config, 'therapy_id': therapy_id}))
        cached = self._store_cache.get(site_id + ':' + (therapy_id or ''))
        if cached and cached['key'] == key and cached['expires'] > time.monotonic():
            return cached['value']
        def read(plan):
            try:
                current, brand, therapy = self.admin.plan_record(plan['id'])
                if current.get('site_id') != site_id or current.get('visibility') != 'public':
                    return None
                return plan, self.admin.plan_options(current, brand, therapy)
            except Exception:
                # A failed upstream catalog must not fabricate purchasable
                # plans or reveal provider errors to a member.
                return None
        results = []
        if published:
            with ThreadPoolExecutor(max_workers=min(4, len(published))) as pool:
                results = list(pool.map(read, published))
        rows, unavailable = [], []
        checkout_origin = getattr(self.cfg, 'checkout_public_url', self.cfg.public_url).rstrip('/')
        for source, result in zip(published, results):
            if result is None:
                unavailable.append(source.get('therapy_id', ''))
                continue
            plan, catalog = result
            for entry in catalog.get('entries', []):
                if not entry.get('available'):
                    continue
                for option in entry.get('options', []):
                    if option.get('blockedReason'):
                        continue
                    try:
                        total = Decimal(str(option.get('upfrontPrice') if option.get('prepaidCycles') else option['basePrice']))
                    except Exception:
                        continue
                    currency = entry.get('currency')
                    currency = currency.upper() if isinstance(currency, str) else ''
                    if not total.is_finite() or total <= 0 or not re.fullmatch('[A-Z]{3}', currency):
                        continue
                    selection = {'sku': entry['sku'], 'option': option['key'], 'purchase_option_id': entry.get('purchaseOptionId', '')}
                    unique = digest(encoded({'checkout': plan['id'], **selection}))[:24]
                    recurring = option.get('renewal') if option.get('prepaidCycles') else option.get('recurring')
                    label = f"{entry.get('durationMonths', '')}-month " + ('subscription' if recurring else 'one-time plan')
                    rows.append({'plan_id': 'portal-choice-' + unique, 'checkout_id': plan['id'],
                        'therapy_id': plan['therapy_id'], 'therapy_name': catalog.get('therapy') or plan['therapy_id'],
                        'product_name': entry.get('name') or entry['sku'], 'plan_name': label,
                        'sku': entry['sku'], 'recurring': recurring if isinstance(recurring, bool) else None,
                        'total': format(total, '.2f'), 'currency': currency,
                        'checkout_url': checkout_origin + '/plans/' + plan['id'] + '/choose?' + urlencode(selection),
                        'payment_test_only': bool(catalog.get('paymentTestOnly'))})
        value = {'site': public_site, 'plans': rows, 'unavailable_therapies': sorted(set(unavailable))}
        self._store_cache[site_id + ':' + (therapy_id or '')] = {'key': key, 'expires': time.monotonic() + 60, 'value': value}
        # Bound the cache to configured sites/therapy tabs, never patient keys.
        if len(self._store_cache) > 100:
            self._store_cache.pop(next(iter(self._store_cache)))
        return value

    def refill_public(self, row):
        with self.db() as db:
            task = db.execute('SELECT task_id,simulated FROM member_refill_tasks WHERE refill_id=?', (row['id'],)).fetchone()
        return {'task_id': task['task_id'] if task else None, 'simulated': bool(task['simulated']) if task else False, 'id': row['id'], 'order_id': row['order_id'], 'sku': row['sku'], 'status': row['status'], 'revision': row['revision'],
                'created_at': stamp(row['created']), 'updated_at': stamp(row['updated']), 'test_only': bool(row['test_only']),
                'rule_revision': json.loads(row['rule']).get('revision', 0), 'kind': row['kind'], 'reason': row['reason'], 'clinical_approval': False, 'fulfillment_created': False}

    def attach(self, app, receipt_access):
        from .cors import PortalCORS
        app.add_middleware(PortalCORS, service=self)
        router = APIRouter(prefix='/api/v1/sites/{site_id}/portal', tags=['Patient portal'])
        owner = APIRouter(prefix='/api/admin/sites/{site_id}/portal', tags=['Site order administration'])
        bearer = HTTPBearer(auto_error=False, scheme_name='PatientSession', description='Site-specific patient access token. Never use payment processor credentials.')

        def auth(site_id: str, req: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
            return self.patient(site_id, req, credentials)

        from .wlmd import IdentityInput

        @router.get('/account/identity')
        def account_identity(site_id: str, patient=Depends(auth)):
            return self.identity_checks.account(site_id, patient)

        @router.get('/orders/{order_id}/identity')
        def order_identity(site_id: str, order_id: str, patient=Depends(auth)):
            return self.identity_checks.status(self.order_record(site_id, order_id, patient), patient)

        @router.post('/orders/{order_id}/identity')
        def verify_order_identity(site_id: str, order_id: str, body: IdentityInput, patient=Depends(auth)):
            return self.identity_checks.verify(self.order_record(site_id, order_id, patient), patient, body)

        from .id_uploads import IDPhotoInput

        @router.get('/orders/{order_id}/id-photo')
        def id_photo_status(site_id: str, order_id: str, patient=Depends(auth)):
            return self.id_uploads.status(self.order_record(site_id, order_id, patient), patient)

        @router.post('/orders/{order_id}/id-photo')
        def id_photo_upload(site_id: str, order_id: str, body: IDPhotoInput, patient=Depends(auth)):
            return self.id_uploads.upload(self.order_record(site_id, order_id, patient), patient, body)

        @router.post('/orders/{order_id}/id-photo/reuse')
        def id_photo_reuse(site_id: str, order_id: str, patient=Depends(auth)):
            return self.id_uploads.upload(self.order_record(site_id, order_id, patient), patient)

        @router.get('/configuration', response_model=ConfigurationResult)
        def configuration(site_id: str):
            _, site = self.site(site_id)
            therapy_ids = {p.get('therapy_id') for p in self.admin.records('plan_checkout') if p.get('site_id') == site_id}
            therapies = [{'id': t, 'name': (self.admin.get('therapy', t) or {}).get('name', t)} for t in sorted(therapy_ids) if t]
            return {'site': site, 'therapies': therapies, 'intake_provider_connected': False, 'messaging_provider_connected': False}

        @router.get('/onboarding', summary='Post-checkout account and intake API contract')
        def onboarding(site_id: str):
            self.site(site_id)
            base = '/api/v1/sites/' + site_id + '/portal'
            return {'version': 2, 'site_id': site_id, 'password_min_length': 12,
                'identity_provider': 'sticky' if self.identity else 'local',
                'enroll_path': base + '/auth/enroll', 'login_path': base + '/auth/login',
                'claim_path': base + '/auth/claim', 'me_path': base + '/me',
                'intake_path': base + '/intakes/{order_id}',
                'intake_submit_path': base + '/intakes/{order_id}/submit',
                'portal_url': self.cfg.public_url + '/portal/' + site_id,
                'intake_provider_connected': False,
                'submission_message': 'Your answers have been saved in your account.'}

        @router.post('/auth/handoff', response_model=AuthResult)
        def handoff(site_id: str, body: ClaimInvite, req: Request):
            self.site(site_id); self.origin(req)
            return self.consume_handoff(site_id, body.invite_token)

        @router.post('/auth/login', response_model=AuthResult)
        def login(site_id: str, body: Login, req: Request):
            self.site(site_id); self.origin(req)
            identity = digest(site_id + ':' + body.email.lower())
            with self.db() as db:
                db.execute('DELETE FROM member_auth_failures WHERE created<?', (self.clock() - 900,))
                failures = db.execute('SELECT COUNT(*) FROM member_auth_failures WHERE site_id=? AND identity_hash=?', (site_id, identity)).fetchone()[0]
                if failures >= 10:
                    raise HTTPException(429, 'Too many sign-in attempts. Please try again later.')
                patient = db.execute('SELECT * FROM member_patients WHERE site_id=? AND email=?', (site_id, body.email.strip().lower())).fetchone()
            if self.identity:
                member = self.authenticate_password(site_id, body.email, body.password)
                if not patient:
                    raise HTTPException(401, 'Open your completed purchase’s portal link to connect your account to this site.')
                return self.session(dict(patient), member)
            candidate = password_hash(body.password, patient['salt'] if patient else '00' * 16)
            if not patient or not hmac.compare_digest(candidate, patient['password_hash']):
                with self.db() as db:
                    db.execute('INSERT INTO member_auth_failures VALUES(?,?,?)', (site_id, identity, self.clock()))
                raise HTTPException(401, 'Email or password is incorrect')
            return self.session(dict(patient))

        @router.post('/auth/logout')
        def logout(site_id: str, patient=Depends(auth), credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
            if self.identity:
                self.identity.logout(digest(credentials.credentials))
                return {'signed_out': True}
            with self.db() as db:
                db.execute('DELETE FROM member_sessions WHERE token_hash=?', (digest(credentials.credentials),))
            return {'signed_out': True}

        @router.post('/auth/enroll', response_model=AuthResult)
        def enroll(site_id: str, body: Enrollment, req: Request):
            self.site(site_id); self.origin(req)
            with self.db() as db:
                invite = db.execute('SELECT * FROM member_invites WHERE token_hash=? AND site_id=? AND used IS NULL AND expires>?', (digest(body.invite_token), site_id, self.clock())).fetchone()
            if not invite:
                raise HTTPException(410, 'This enrollment invitation expired or was already used')
            order = self.sync(site_id, invite['order_id'])
            if order['customer_id'] != invite['customer_id']:
                raise HTTPException(409, 'The order identity changed; contact the site')
            return self.enroll(site_id, order, body.password, 'owner_invitation', body.invite_token)

        @router.post('/auth/receipt', response_model=AuthResult)
        def receipt_enroll(site_id: str, body: ReceiptEnrollment, req: Request):
            if receipt_access is None:
                raise HTTPException(503, 'Receipt enrollment is not configured')
            self.site(site_id); self.origin(req)
            attempt = receipt_access(req, mutation=True)
            if not attempt or attempt.get('status') != 'captured' or not attempt.get('order_id'):
                raise HTTPException(409, 'Finish this checkout before creating its patient account')
            candidates = self.captured(site_id, str(attempt['order_id']))
            if not any(row['id'] == attempt['id'] for row in candidates):
                raise HTTPException(403, 'This receipt does not belong to this site')
            order = self.sync(site_id, str(attempt['order_id']))
            return self.enroll(site_id, order, body.password, 'checkout_receipt')

        @router.post('/auth/claim')
        def claim(site_id: str, body: ClaimInvite, patient=Depends(auth)):
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                invite = db.execute('SELECT * FROM member_invites WHERE token_hash=? AND site_id=? AND expires>?', (digest(body.invite_token), site_id, self.clock())).fetchone()
                if not invite:
                    raise HTTPException(403, 'This invitation cannot be connected to this account')
                # Separate cart orders may have separate Sticky customer IDs.
                # Require both the private receipt invitation AND authenticated
                # account identity; email alone never imports or grants an order.
                order = db.execute('SELECT payload FROM member_orders WHERE site_id=? AND order_id=?', (site_id, invite['order_id'])).fetchone()
                contact = json.loads(order['payload']).get('customer', {}) if order else {}
                if str(contact.get('email', '')).strip().lower() != patient['email'].strip().lower():
                    raise HTTPException(403, 'This invitation cannot be connected to this account')
                existing = db.execute('SELECT patient_id FROM member_grants WHERE site_id=? AND order_id=?', (site_id, invite['order_id'])).fetchone()
                if existing and existing['patient_id'] != patient['id']:
                    raise HTTPException(409, 'This order is already assigned to another account')
                if invite['used'] is not None:
                    if existing and existing['patient_id'] == patient['id']:
                        return {'connected': True}
                    raise HTTPException(403, 'This invitation has already been used')
                db.execute('INSERT OR IGNORE INTO member_grants VALUES(?,?,?,?,?)', (site_id, invite['order_id'], patient['id'], self.clock(), 'owner_invitation'))
                db.execute('UPDATE member_invites SET used=? WHERE token_hash=?', (self.clock(), digest(body.invite_token)))
            self.adopt_receipt_intake(self.order_record(site_id, invite['order_id'], patient), patient)
            return {'connected': True}

        @router.get('/me', response_model=MeResult)
        def me(site_id: str, patient=Depends(auth)):
            return {'site': self.site(site_id)[1], 'patient': self.patient_public(patient)}

        @router.get('/store', response_model=StoreResult)
        def store(site_id: str, therapy_id: str | None = None, patient=Depends(auth)):
            return self.store_catalog(site_id, therapy_id)

        @router.get('/orders', response_model=OrdersResult)
        def orders(site_id: str, therapy_id: str | None = None, patient=Depends(auth)):
            return {'orders': self.order_list(site_id, patient, therapy_id)}

        @router.get('/orders/{order_id}', response_model=OrderModel)
        def order(site_id: str, order_id: str, patient=Depends(auth)):
            return self.order_public(self.order_record(site_id, order_id, patient))

        @router.post('/orders/{order_id}/refresh', response_model=OrderModel)
        def refresh_order(site_id: str, order_id: str, patient=Depends(auth)):
            self.order_record(site_id, order_id, patient)
            return self.order_public(self.sync(site_id, order_id))

        @router.post('/orders/{order_id}/subscriptions/{subscription_id}/pause', response_model=OrderModel)
        @router.post('/orders/{order_id}/subscriptions/{subscription_id}/resume', response_model=OrderModel)
        def subscription(site_id: str, order_id: str, subscription_id: str, body: ActionBody, req: Request, patient=Depends(auth)):
            action = req.url.path.rsplit('/', 1)[-1]
            self.order_record(site_id, order_id, patient)
            row = self.sync(site_id, order_id)
            raw = json.loads(row['payload'])
            line = next((p for p in raw['products'] if str(p.get('subscription_id')) == subscription_id), None)
            if not line:
                raise HTTPException(404, 'Subscription not found in this order')
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                if self.upgrades.busy_subscription(site_id, subscription_id):
                    raise HTTPException(409, 'This subscription has a replacement checkout. Open Refills to review it.')
                previous = db.execute('SELECT * FROM member_actions WHERE site_id=? AND patient_id=? AND client_request_id=?', (site_id, patient['id'], body.client_request_id)).fetchone()
                if previous:
                    if (previous['order_id'], previous['subscription_id'], previous['action']) != (order_id, subscription_id, action):
                        raise HTTPException(409, 'This request ID was already used for a different action')
                    if previous['status'] != 'complete':
                        raise HTTPException(409, 'This subscription action needs review before retrying')
                    return self.order_public(row)
                if db.execute("SELECT 1 FROM member_actions WHERE site_id=? AND subscription_id=? AND status IN ('pending','uncertain')", (site_id, subscription_id)).fetchone():
                    raise HTTPException(409, 'An earlier subscription action needs review')
                action_id = identifier('action')
                db.execute('INSERT INTO member_actions VALUES(?,?,?,?,?,?,?,?,?)', (action_id, site_id, patient['id'], order_id, subscription_id, action, body.client_request_id, 'pending', self.clock()))
            try:
                self.provider.subscription_action(order_id, subscription_id, action, expected_campaign=self.site(site_id)[0]['campaign_id'], expected_customer_id=row['customer_id'])
                updated = self.sync(site_id, order_id)
            except ProviderError:
                with self.db() as db:
                    db.execute("UPDATE member_actions SET status='uncertain' WHERE id=?", (action_id,))
                raise HTTPException(409, 'The subscription change needs reconciliation. It will not be retried automatically.') from None
            except HTTPException:
                with self.db() as db:
                    db.execute("UPDATE member_actions SET status='uncertain' WHERE id=?", (action_id,))
                raise
            with self.db() as db:
                db.execute("UPDATE member_actions SET status='complete' WHERE id=?", (action_id,))
            return self.order_public(updated)

        @router.get('/orders/{order_id}/payment-method', response_model=CapabilityResult)
        def payment_method(site_id: str, order_id: str, patient=Depends(auth)):
            self.order_record(site_id, order_id, patient)
            return {'available': False, 'reason': 'Secure payment-method updates are not connected yet. Contact the site for assistance; never send card details in a message.'}

        @router.get('/orders/{order_id}/subscriptions/{subscription_id}/address')
        def read_subscription_address(site_id: str, order_id: str, subscription_id: str, patient=Depends(auth)):
            row = self.order_record(site_id, order_id, patient)
            raw = json.loads(row['payload'])
            if not any(str(p.get('subscription_id')) == subscription_id for p in raw['products']):
                raise HTTPException(404, 'Subscription not found in this order')
            try:
                address = self.provider.read_subscription_address(order_id, subscription_id,
                    expected_campaign=self.site(site_id)[0]['campaign_id'], expected_customer_id=row['customer_id'])
            except ProviderError:
                raise HTTPException(502, 'The current subscription address could not be verified. Please try again later.') from None
            return {'address': address, 'scope': 'future_subscription'}

        @router.post('/orders/{order_id}/subscriptions/{subscription_id}/address', response_model=OrderModel)
        def update_subscription_address(site_id: str, order_id: str, subscription_id: str, body: AddressBody, patient=Depends(auth)):
            self.order_record(site_id, order_id, patient)
            row = self.sync(site_id, order_id)
            raw = json.loads(row['payload'])
            if not any(str(p.get('subscription_id')) == subscription_id for p in raw['products']):
                raise HTTPException(404, 'Subscription not found in this order')
            address = body.address.model_dump()
            action = 'subscription_address:' + digest(encoded(address))
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                if self.upgrades.busy_subscription(site_id, subscription_id):
                    raise HTTPException(409, 'This subscription has a replacement checkout. Open Refills to review it.')
                previous = db.execute('SELECT * FROM member_actions WHERE site_id=? AND patient_id=? AND client_request_id=?', (site_id, patient['id'], body.client_request_id)).fetchone()
                if previous:
                    if (previous['order_id'], previous['subscription_id'], previous['action']) != (order_id, subscription_id, action):
                        raise HTTPException(409, 'This request ID was used for a different update')
                    if previous['status'] != 'complete':
                        raise HTTPException(409, 'The previous subscription-address update needs review')
                    return self.order_public(row)
                if db.execute("SELECT 1 FROM member_actions WHERE site_id=? AND subscription_id=? AND status IN ('pending','uncertain')", (site_id, subscription_id)).fetchone():
                    raise HTTPException(409, 'An earlier subscription update needs review')
                action_id = identifier('action')
                db.execute('INSERT INTO member_actions VALUES(?,?,?,?,?,?,?,?,?)', (action_id, site_id, patient['id'], order_id, subscription_id, action, body.client_request_id, 'pending', self.clock()))
            try:
                updated_remote = self.provider.update_subscription_address(order_id, subscription_id, address, expected_campaign=self.site(site_id)[0]['campaign_id'], expected_customer_id=row['customer_id'])
                self.save_order(site_id, order_id, row['customer_id'], row['attempt_id'], row['therapy_id'], row['sku'], json.loads(row['snapshot']), updated_remote)
            except ProviderRejected:
                with self.db() as db:
                    db.execute("UPDATE member_actions SET status='rejected' WHERE id=?", (action_id,))
                raise HTTPException(409, 'The subscription address could not be updated. Keep the existing recipient name and address line 2, or contact the site.') from None
            except (ProviderError, HTTPException):
                with self.db() as db:
                    db.execute("UPDATE member_actions SET status='uncertain' WHERE id=?", (action_id,))
                raise HTTPException(409, 'The subscription-address update needs reconciliation. It will not be sent again automatically.') from None
            with self.db() as db:
                db.execute("UPDATE member_actions SET status='complete' WHERE id=?", (action_id,))
            return self.order_public(self.order_record(site_id, order_id, patient))

        @router.post('/orders/{order_id}/address', response_model=OrderModel)
        def update_address(site_id: str, order_id: str, body: AddressBody, patient=Depends(auth)):
            self.order_record(site_id, order_id, patient)
            row = self.sync(site_id, order_id)
            address = body.address.model_dump()
            action = 'address:' + digest(encoded(address))
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                previous = db.execute('SELECT * FROM member_actions WHERE site_id=? AND patient_id=? AND client_request_id=?', (site_id, patient['id'], body.client_request_id)).fetchone()
                if previous:
                    if (previous['order_id'], previous['action']) != (order_id, action):
                        raise HTTPException(409, 'This request ID was used for a different update')
                    if previous['status'] != 'complete':
                        raise HTTPException(409, 'The previous address update needs review before retrying')
                    return self.order_public(row)
                if not self.order_public(row)['address_update_available']:
                    raise HTTPException(409, 'This order cannot safely change its delivery address online. Contact the site.')
                if db.execute("SELECT 1 FROM member_actions WHERE site_id=? AND order_id=? AND action LIKE 'address:%' AND status IN ('pending','uncertain')", (site_id, order_id)).fetchone():
                    raise HTTPException(409, 'An earlier address update needs review')
                action_id = identifier('action')
                db.execute('INSERT INTO member_actions VALUES(?,?,?,?,?,?,?,?,?)', (action_id, site_id, patient['id'], order_id, '', action, body.client_request_id, 'pending', self.clock()))
            try:
                self.provider.update_address(order_id, address, expected_campaign=self.site(site_id)[0]['campaign_id'], expected_customer_id=row['customer_id'])
                updated = self.sync(site_id, order_id)
            except ProviderRejected:
                with self.db() as db:
                    db.execute("UPDATE member_actions SET status='rejected' WHERE id=?", (action_id,))
                raise HTTPException(409, 'This order cannot safely change its delivery address online. Contact the site.') from None
            except (ProviderError, HTTPException):
                with self.db() as db:
                    db.execute("UPDATE member_actions SET status='uncertain' WHERE id=?", (action_id,))
                raise HTTPException(409, 'The address update needs reconciliation. It will not be sent again automatically.') from None
            with self.db() as db:
                db.execute("UPDATE member_actions SET status='complete' WHERE id=?", (action_id,))
            return self.order_public(updated)

        @router.get('/intakes/{order_id}', response_model=MemberIntakeResponse)
        def get_intake(site_id: str, order_id: str, patient=Depends(auth)):
            order = self.order_record(site_id, order_id, patient)
            return self.initial_intake(order, patient)

        @router.patch('/intakes/{order_id}', response_model=MemberIntakeResponse)
        def save_intake(site_id: str, order_id: str, body: IntakePatch, patient=Depends(auth)):
            return self.modify_initial(self.order_record(site_id, order_id, patient), body, patient)

        @router.post('/intakes/{order_id}/submit', response_model=MemberIntakeResponse)
        def submit_intake(site_id: str, order_id: str, body: IntakeSubmit, patient=Depends(auth)):
            return self.modify_initial(self.order_record(site_id, order_id, patient), body, patient, True)

        @router.get('/messages', response_model=MessagesResult)
        def messages(site_id: str, patient=Depends(auth)):
            return {'messages': self.messages(site_id, patient['id']), 'provider_connected': False}

        @router.get('/messages/draft', response_model=MessageDraft)
        def message_draft(site_id: str, patient=Depends(auth)):
            return self.message_draft(site_id, patient['id'])

        @router.put('/messages/draft', response_model=MessageDraft)
        def save_message_draft(site_id: str, body: MessageDraftSave, patient=Depends(auth)):
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT * FROM member_message_drafts WHERE site_id=? AND patient_id=?', (site_id, patient['id'])).fetchone()
                if (row['revision'] if row else 0) != body.revision:
                    raise HTTPException(409, 'Your saved draft changed in another window. Keep your message and reload the saved draft before replacing it.')
                db.execute('INSERT INTO member_message_drafts VALUES(?,?,?,?,?) ON CONFLICT(site_id,patient_id) DO UPDATE SET body=excluded.body,revision=excluded.revision,updated=excluded.updated',
                    (site_id, patient['id'], body.body, body.revision + 1, self.clock()))
            return self.message_draft(site_id, patient['id'])

        @router.get('/notifications', response_model=NotificationsResult)
        def notifications(site_id: str, patient=Depends(auth)):
            return self.notifications(site_id, patient)

        @router.post('/notifications/{notification_id}/read', response_model=NotificationsResult)
        def read_notification(site_id: str, notification_id: str, patient=Depends(auth)):
            current = self.notifications(site_id, patient)
            if notification_id not in {item['id'] for item in current['notifications']}:
                raise HTTPException(404, 'This update is no longer available')
            with self.db() as db:
                db.execute('INSERT OR IGNORE INTO member_notification_reads VALUES(?,?,?,?)',
                    (site_id, patient['id'], notification_id, self.clock()))
            return self.notifications(site_id, patient)

        @router.post('/messages', response_model=MessagesResult)
        def message(site_id: str, body: MessageBody, patient=Depends(auth)):
            content = body.body.strip()
            if not content:
                raise HTTPException(422, 'Enter a message')
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                prior = db.execute("SELECT body FROM member_messages WHERE site_id=? AND patient_id=? AND client_message_id=? AND sender='patient'", (site_id, patient['id'], body.client_message_id)).fetchone()
                if prior and prior['body'] != content:
                    raise HTTPException(409, 'This message ID was already used with different text')
                if not prior:
                    count = db.execute('SELECT COUNT(*) FROM member_messages WHERE site_id=? AND patient_id=?', (site_id, patient['id'])).fetchone()[0]
                    if count >= 500:
                        raise HTTPException(429, 'Message limit reached. Contact the site for assistance.')
                    for sender, text in [('patient', content), ('system', 'Automatic acknowledgement: your message is saved in this portal. The medical messaging API is not connected, so no clinician has received it. Please use the site’s support contact for care questions.')]:
                        db.execute('INSERT INTO member_messages VALUES(?,?,?,?,?,?,?)', (identifier('message'), site_id, patient['id'], sender, text, self.clock(), body.client_message_id))
            return {'messages': self.messages(site_id, patient['id']), 'provider_connected': False}

        @router.get('/refills', response_model=RefillsResult)
        def refills(site_id: str, patient=Depends(auth)):
            with self.db() as db:
                rows = db.execute('SELECT * FROM member_refills WHERE site_id=? AND patient_id=? ORDER BY created DESC', (site_id, patient['id'])).fetchall()
            return {'requests': [self.refill_public(row) for row in rows]}

        @router.post('/refills', response_model=RefillResult)
        def request_refill(site_id: str, body: RefillBody, patient=Depends(auth)):
            self.order_record(site_id, body.order_id, patient)
            # Return an already accepted request before evaluating a later
            # cooldown or billing change; retries never create a second request.
            with self.db() as db:
                prior = db.execute('SELECT * FROM member_refills WHERE site_id=? AND patient_id=? AND client_request_id=?', (site_id, patient['id'], body.client_request_id)).fetchone()
            if prior:
                if (prior['order_id'], prior['sku'], prior['kind'], prior['reason']) != (body.order_id, body.sku, body.kind, body.reason.strip()) or self.refill_public(prior).get('task_id') != body.task_id:
                    raise HTTPException(409, 'This request ID was already used for another refill')
                return {'request': self.refill_public(prior)}
            order = self.sync(site_id, body.order_id)
            if order['sku'] != body.sku:
                raise HTTPException(404, 'This SKU is not in your order')
            availability = self.refill_availability(order, body.task_id) if body.task_id else self.refill_availability(order)
            if self.care.configured(order) and body.task_id is None:
                raise HTTPException(422, 'Choose the care checkpoint for this refill request')
            if body.kind == 'early':
                if not availability.get('early_allowed'):
                    raise HTTPException(409, availability.get('early_reason') or availability['reason'])
            elif not availability['eligible']:
                raise HTTPException(409, availability['reason'])
            rule = self.care.settings(order) if self.care.configured(order) else self.rule(body.sku, site_id)
            if body.kind == 'early' and rule.get('early_reason_required', True) and not body.reason.strip():
                raise HTTPException(422, 'Tell the review team why you are requesting an early refill')
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                prior = db.execute('SELECT * FROM member_refills WHERE site_id=? AND patient_id=? AND client_request_id=?', (site_id, patient['id'], body.client_request_id)).fetchone()
                if prior:
                    if (prior['order_id'], prior['sku'], prior['kind'], prior['reason']) != (body.order_id, body.sku, body.kind, body.reason.strip()) or self.refill_public(prior).get('task_id') != body.task_id:
                        raise HTTPException(409, 'This request ID was already used for another refill')
                    return {'request': self.refill_public(prior)}
                existing = db.execute("SELECT * FROM member_refills WHERE site_id=? AND patient_id=? AND sku=? AND cycle_key=? AND status NOT IN ('declined')", (site_id, patient['id'], body.sku, availability['_cycle_key'])).fetchone()
                if existing:
                    return {'request': self.refill_public(existing)}
                # Availability was checked before the transaction. Recheck the
                # patient/SKU cooldown under this write lock so parallel requests
                # against different orders cannot each consume the same window.
                if body.kind == 'early':
                    latest = self.care.last_early(db, order, patient['id'])
                    if latest is not None and self.care.clock(order) < latest + int(rule.get('early_request_cooldown_days', 7)) * 86400:
                        raise HTTPException(409, 'The waiting period after your previous early refill request has not ended.')
                key, now = identifier('refill'), self.care.clock(order)
                status = 'awaiting_review' if body.kind == 'early' or availability.get('_plan_id') else 'check_in_required' if rule.get('check_in_required', True) else 'requested'
                db.execute('INSERT INTO member_refills VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (key, site_id, patient['id'], body.order_id, body.sku, availability['_cycle_key'], status, 0, encoded(rule), int(availability['test_only']), now, now, '', body.client_request_id, body.kind, body.reason.strip()))
                if availability.get('_plan_id'):
                    db.execute('INSERT INTO member_refill_tasks VALUES(?,?,?,?)', (key, availability['_plan_id'], body.task_id, int(availability.get('_simulated', False))))
                row = db.execute('SELECT * FROM member_refills WHERE id=?', (key,)).fetchone()
            return {'request': self.refill_public(row)}

        @owner.get('/refill-rules')
        def site_refill_rules(site_id: str, req: Request):
            self.admin.authenticated(req)
            return {'site_id': site_id, 'rules': [self.site_rule_public(site_id, sku, product)
                    for sku, product in sorted(self.site_rule_products(site_id).items())]}

        @owner.put('/refill-rules/{sku}')
        def save_site_refill_rules(site_id: str, sku: str, body: SaveRefillRules, req: Request):
            self.admin.authenticated(req, True)
            products = self.site_rule_products(site_id)
            if sku not in products:
                raise HTTPException(404, 'This product is not assigned to the selected site')
            from .intake_templates import binding_for_sku
            binding = binding_for_sku(sku)
            if body.intake_template_id and (not binding or binding['template_id'] != body.intake_template_id):
                raise HTTPException(422, 'Choose the intake assigned to this product')
            if body.check_in_days and not body.intake_template_id:
                raise HTTPException(422, 'Choose a product intake before scheduling check-ins')
            setup = products[sku].get('product_setup') or {}
            from refill_rules import validate_included_policy
            validate_included_policy(body, binding, setup)
            key = site_rule_key(site_id, sku)
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute("SELECT data FROM admin_config WHERE kind='site_refill_policy' AND id=?", (key,)).fetchone()
                previous = json.loads(row[0]) if row else {'revision': 0}
                if previous['revision'] != body.expected_revision:
                    raise HTTPException(409, 'These site refill settings changed. Reload before saving.')
                value = dict(body.model_dump(exclude={'expected_revision'}), site_id=site_id, sku=sku, revision=previous['revision'] + 1)
                db.execute("INSERT INTO admin_config(kind,id,data) VALUES('site_refill_policy',?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data", (key, json.dumps(value)))
            return self.site_rule_public(site_id, sku, products[sku])

        @owner.get('/overview')
        def overview(site_id: str, req: Request, therapy_id: str | None = None):
            self.admin.authenticated(req)
            _, site = self.site(site_id)
            orders = self.order_list(site_id, therapy_id=therapy_id)
            order_ids = {o['id'] for o in orders}
            with self.db() as db:
                intakes = db.execute('SELECT i.*,p.name FROM member_intakes i JOIN member_patients p ON p.id=i.patient_id WHERE i.site_id=?', (site_id,)).fetchall()
                refills = db.execute('SELECT * FROM member_refills WHERE site_id=? ORDER BY created DESC', (site_id,)).fetchall()
            summaries = []
            for row in intakes:
                if row['order_id'] not in order_ids:
                    continue
                order = next(o for o in orders if o['id'] == row['order_id'])
                answers = json.loads(row['answers'])
                questions = [q for q in json.loads(row['template'])['questions'] if visible(q, answers)]
                summaries.append({'id': row['id'], 'order_id': row['order_id'], 'patient_name': row['name'], 'therapy_id': order['therapy_id'],
                                  'therapy_name': order['therapy_name'], 'status': row['status'], 'answered': sum(answers.get(q['id']) not in (None, '', []) for q in questions),
                                  'total': len(questions), 'updated_at': stamp(row['updated'])})
            with self.db() as db:
                care_rows = db.execute('''SELECT i.*,NULL AS claim_id,NULL AS claim_order_id,c.site_id,c.root_order_id,c.term_order_id,c.patient_id,
                    c.snapshot AS care_snapshot,p.name FROM member_care_intakes i
                    JOIN member_care_plans c ON c.id=i.plan_id
                    JOIN member_patients p ON p.id=c.patient_id AND p.site_id=c.site_id WHERE c.site_id=?''', (site_id,)).fetchall()
                care_rows = list(care_rows) + list(db.execute('''SELECT i.*,c.site_id,c.root_order_id,c.term_order_id,c.patient_id,
                    c.snapshot AS care_snapshot,p.name FROM member_claim_intakes i
                    JOIN member_care_plans c ON c.id=i.plan_id
                    JOIN member_patients p ON p.id=c.patient_id AND p.site_id=c.site_id WHERE c.site_id=?''', (site_id,)).fetchall())
                scoped_orders = db.execute('SELECT order_id,snapshot FROM member_orders WHERE site_id=?', (site_id,)).fetchall()
            care_ids = {row['id'] for row in care_rows}
            summaries = [summary for summary in summaries if summary['id'] not in care_ids]
            for row in care_rows:
                matches = [o['order_id'] for o in scoped_orders if o['order_id'] in order_ids
                    and json.loads(o['snapshot']).get('root_order_id') == row['root_order_id']
                    and json.loads(o['snapshot']).get('term_order_id') == row['term_order_id']]
                if not matches:
                    continue
                order_id = row['claim_order_id'] if row['claim_order_id'] in matches else max(matches, key=int)
                order = next(o for o in orders if o['id'] == order_id)
                answers = json.loads(row['answers'])
                questions = [q for q in json.loads(row['template'])['questions'] if visible(q, answers)]
                task_label = 'Initial health intake' if row['task_id'] == 'initial' else 'Day ' + row['task_id'].removeprefix('checkin-') + ' check-in'
                summaries.append({'id': row['id'], 'order_id': order_id, 'patient_name': row['name'],
                    'therapy_id': order['therapy_id'], 'therapy_name': order['therapy_name'], 'task_id': row['task_id'], 'task_label': task_label,
                    'status': row['status'], 'answered': sum(answers.get(q['id']) not in (None, '', []) for q in questions),
                    'total': len(questions), 'updated_at': stamp(row['updated']), 'simulated': bool(row['simulated']),
                    'claim_id': row['claim_id'], 'claim_order_id': row['claim_order_id']})
            requests = [self.refill_public(r) for r in refills if r['order_id'] in order_ids]
            return {'site': site, 'orders': orders, 'intakes': summaries, 'refills': requests, 'leads': [],
                    'summaries': {'orders': len(orders), 'intake_drafts': sum(i['status'] == 'draft' for i in summaries), 'intakes_submitted': sum(i['status'] == 'submitted' for i in summaries), 'refill_requests': len(requests)}}

        @owner.post('/sync', response_model=OrdersResult)
        def synchronize(site_id: str, body: SyncBody, req: Request):
            self.admin.authenticated(req, True)
            self.site(site_id)
            keys = body.order_ids or list(dict.fromkeys(row['order_id'] for row in self.captured(site_id)))[:50]
            if (body.allow_historical or body.allow_import) and not body.order_ids:
                raise HTTPException(422, 'List exact historical order IDs before assigning them to a site')
            for key in keys:
                self.sync(site_id, key, allow_historical=body.allow_historical, allow_import=body.allow_import)
            return {'orders': self.order_list(site_id)}

        @owner.post('/invites')
        def invite(site_id: str, body: InviteBody, req: Request):
            self.admin.authenticated(req, True)
            order = self.sync(site_id, body.order_id)
            return self.issue_invite(site_id, order)

        @owner.patch('/refills/{request_id}', response_model=RefillResult)
        def review_refill(site_id: str, request_id: str, body: ReviewRefill, req: Request):
            self.admin.authenticated(req, True)
            self.site(site_id)
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT * FROM member_refills WHERE id=? AND site_id=?', (request_id, site_id)).fetchone()
                if not row:
                    raise HTTPException(404, 'Refill request not found')
                if row['revision'] != body.revision:
                    raise HTTPException(409, 'This refill request changed. Reload before updating.')
                db.execute('UPDATE member_refills SET status=?,note=?,revision=revision+1,updated=? WHERE id=?', (body.status, body.note, self.clock(), request_id))
                row = db.execute('SELECT * FROM member_refills WHERE id=?', (request_id,)).fetchone()
            return {'request': self.refill_public(row)}

        @app.get('/api/admin/portal/sites', tags=['Site order administration'])
        def admin_sites(req: Request):
            self.admin.authenticated(req)
            return {'sites': [{k: site.get(k) for k in ('id', 'name', 'brand_id', 'campaign_id')} for site in self.admin.records('site')]}

        self.care.attach(router, owner, auth)
        self.claims.attach(router, auth)
        self.renewals.attach(router, auth)
        self.upgrades.attach(app, router, auth)
        app.include_router(router)
        app.include_router(owner)

        @app.get('/portal/{site_id}', include_in_schema=False)
        @app.get('/portal-admin/{site_id}', include_in_schema=False)
        def portal_page(site_id: str):
            self.site(site_id)
            return FileResponse(HERE / 'web' / 'index.html', media_type='text/html')

        @app.get('/portal-assets/{name}', include_in_schema=False)
        def asset(name: str):
            if name not in ('post-checkout.js', 'id-upload.js', 'portal-checkout.js', 'portal.js', 'portal.css', 'red-hat-display-latin-v1.woff2', 'red-hat-display-OFL.txt'):
                raise HTTPException(404, 'Asset not found')
            return FileResponse(HERE / 'web' / name, headers={'Access-Control-Allow-Origin': '*'} if name == 'id-upload.js' else None)

        @app.get('/portal-assets/fortifyhp/{name}', include_in_schema=False)
        def fortify_asset(name: str):
            if name not in ('logo.png', 'code-pro.ttf'):
                raise HTTPException(404, 'Asset not found')
            return FileResponse(HERE / 'web' / 'fortifyhp' / name,
                                media_type='image/png' if name == 'logo.png' else 'font/ttf')

        @app.get('/portal/{site_id}/openapi.json', include_in_schema=False)
        def schema(site_id: str):
            _, site = self.site(site_id)
            spec = get_openapi(title=site['name'] + ' · Patient portal API', version='0.1.0', routes=app.routes,
                              description='Real site-bound Sticky orders and explicit patient order grants. Intake questions and care messaging are placeholders until their provider APIs are connected. Refills are review requests only; no charge, shipment or clinical approval is created.')
            paths = {}
            for path, operations in spec['paths'].items():
                if path.startswith('/api/v1/sites/{site_id}/portal/'):
                    for operation in operations.values():
                        operation['parameters'] = [p for p in operation.get('parameters', []) if p.get('name') != 'site_id']
                    paths[path.replace('{site_id}', site_id)] = operations
            spec['paths'] = paths
            spec['servers'] = [{'url': self.cfg.public_url or '/'}]
            return spec

        @app.get('/portal/{site_id}/docs', include_in_schema=False)
        def docs(site_id: str):
            _, site = self.site(site_id)
            return get_swagger_ui_html(openapi_url='/portal/' + site_id + '/openapi.json', title=site['name'] + ' · Patient portal API',
                                      swagger_favicon_url='data:,', swagger_ui_parameters={'persistAuthorization': False})
