"""Site-scoped payment APIs. Delegates to the unchanged durable checkout engine.

Only checkout-owned browser cookies/attempts live here. No Sticky/Stripe account
credentials, card data, processor secrets or automatic financial retries.
"""
import hashlib
import hmac
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import http.client
from http.cookies import SimpleCookie
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import ssl
import threading
import time
from urllib import parse
import weakref

from fastapi import APIRouter, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator

PUBLIC_UPSTREAM = 'https://wlmd-stripe-test-0f89b1bb.fly.dev'
SESSION_TTL = 86400
US_REGIONS = set('AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY AS GU MP PR VI AA AE AP'.split())


class StrictBody(BaseModel):
    model_config = ConfigDict(extra='forbid',str_strip_whitespace=True)

class CreateSession(StrictBody):
    model_config=ConfigDict(extra='forbid',json_schema_extra={'example':{'plan_id':'sema-1m'}})
    plan_id: str = Field(min_length=1,max_length=80)

class Contact(StrictBody):
    name: str = Field(min_length=2,max_length=100)
    email: str = Field(min_length=5,max_length=254)
    phone: str = Field(min_length=7,max_length=30)
    address: str = Field(min_length=2,max_length=150)
    city: str = Field(min_length=1,max_length=80)
    region: str = Field(min_length=1,max_length=80)
    postal_code: str = Field(min_length=2,max_length=20)
    country: str = Field(pattern=r'^[A-Z]{2}$')

    @field_validator('email')
    @classmethod
    def email_valid(cls,value):
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value):
            raise ValueError('Enter a valid email')
        return value

    @field_validator('phone')
    @classmethod
    def phone_valid(cls,value):
        if not 7 <= len(re.sub(r'\D','',value)) <= 15:
            raise ValueError('Enter a valid phone')
        return value

class QuoteBody(StrictBody):
    model_config=ConfigDict(extra='forbid',json_schema_extra={'example':{'contact':{'name':'API Integration Test','email':'customer@example.invalid','phone':'+12025550100','address':'1 Test Way','city':'San Francisco','region':'CA','postal_code':'94105','country':'US'},'shipping_id':None}})
    contact: Contact
    shipping_id: int | None = Field(default=None,gt=0)
    dollar_test: bool = False

class PaymentBody(StrictBody):
    model_config=ConfigDict(extra='forbid',json_schema_extra={'example':{'quote_id':'COPY_QUOTE_ID','accept_terms':False}})
    quote_id: str = Field(min_length=1,max_length=100)
    accept_terms: bool = False

class CompleteBody(StrictBody):
    model_config=ConfigDict(extra='forbid',json_schema_extra={'example':{'payment_intent_id':'pi_ReplaceWithStripeIntentId'}})
    payment_intent_id: str = Field(pattern=r'^pi_[A-Za-z0-9]+$',max_length=100)

class Empty(StrictBody):
    pass

class SessionCreated(BaseModel):
    session_id: str
    session_token: str
    expires_at: int
    plan_id: str
    status: str

class SessionStatus(BaseModel):
    session_id: str
    plan_id: str
    status: str
    amount: int | None = None
    currency: str | None = None
    payment_intent_id: str | None = None
    order_id: str | None = None

class Configuration(BaseModel):
    publishable_key: str
    currency: str
    countries: list[dict]
    shipping: list[dict]
    plan: dict
    payment_test_only: bool
    dollar_test_available: bool = False


class DisplayConfigurationCache:
    """Short-lived public display data only; payment paths never consult this.

    Each key has one loader. Followers still verify their own upstream visit
    before using the shared result. Expired data is never served after failure.
    """
    def __init__(self,clock=time.monotonic,ttl=60,limit=1000):
        self.clock,self.ttl,self.limit=clock,ttl,limit
        self.entries=OrderedDict();self.guard=threading.Lock()
        self.locks=weakref.WeakValueDictionary()

    def get(self,key,loader,check_access):
        with self.guard:
            key_lock=self.locks.get(key)
            if key_lock is None:
                key_lock=threading.Lock();self.locks[key]=key_lock
        with key_lock:
            with self.guard:
                entry=self.entries.get(key)
                hit=entry is not None and entry[0]>self.clock()
                if hit:payload=entry[1]
                elif entry is not None:del self.entries[key]
            if not hit:
                # Serialize the explicit response model rather than storing an
                # upstream response (which includes CSRF and attempt details).
                payload=loader().model_dump_json()
                with self.guard:
                    now=self.clock()
                    for expired in [k for k,v in self.entries.items() if v[0]<=now]:
                        del self.entries[expired]
                    while len(self.entries)>=self.limit:
                        self.entries.popitem(last=False)
                    self.entries[key]=(now+self.ttl,payload)
        if hit:
            check_access()
        # Each caller receives its own value; mutation cannot pollute the cache.
        return Configuration.model_validate_json(payload)

class QuoteResult(BaseModel):
    quote_id: str
    amount: int
    currency: str
    payment_terms: str
    terms_consent_required: bool

class PaymentResult(BaseModel):
    payment_intent_id: str
    client_secret: str
    publishable_key: str
    amount: int
    currency: str
    status: str = 'awaiting_card'

class PortalEnrollmentResult(BaseModel):
    site_id: str = Field(description='This Site API site id')
    portal_site_id: str = Field(description='Member portal site id from the admin (the /portal/{id} path)')
    enrollment_url: str = Field(description='One-time account invitation link (expires after one hour); open it in the customer browser')
    expires_at: str | None = None


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class SessionStore:
    def __init__(self,directory,clock=time.time):
        directory=Path(directory);directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.path=directory/'api-sessions.sqlite3';self.clock=clock
        self.locks=weakref.WeakValueDictionary();self.lock_guard=threading.Lock()
        with self.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS api_sessions(
                id TEXT PRIMARY KEY,token_hash TEXT NOT NULL,site_id TEXT NOT NULL,
                plan_id TEXT NOT NULL,link_id TEXT NOT NULL,selection TEXT NOT NULL,
                created REAL NOT NULL,expires REAL NOT NULL,cookies TEXT NOT NULL,
                csrf TEXT NOT NULL,attempt TEXT NOT NULL,phase TEXT NOT NULL,
                busy TEXT,held TEXT,quote_id TEXT,publishable_key TEXT)''')
            # A restart must never silently retry an operation whose reply was lost.
            db.execute("UPDATE api_sessions SET held=CASE busy WHEN 'authorize' THEN 'authorization_unknown' ELSE 'capture_unknown' END,busy=NULL WHERE busy IS NOT NULL")
        self.path.chmod(0o600)

    def db(self):
        db=sqlite3.connect(self.path,timeout=10);db.row_factory=sqlite3.Row
        return db

    def read(self,key):
        with self.db() as db:
            row=db.execute('SELECT * FROM api_sessions WHERE id=?',(key,)).fetchone()
        return dict(row) if row else None

    def create(self,site_id,plan_id,link_id,selection):
        key=secrets.token_urlsafe(24);token=secrets.token_urlsafe(32);now=self.clock()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT COUNT(*) FROM api_sessions WHERE expires>?',(now,)).fetchone()[0]>=1000:
                raise HTTPException(429,'Checkout session limit reached; try again later')
            db.execute('INSERT INTO api_sessions(id,token_hash,site_id,plan_id,link_id,selection,created,expires,cookies,csrf,attempt,phase) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (key,digest(token),site_id,plan_id,link_id,selection,now,now+SESSION_TTL,'{}','','','initializing'))
        return self.read(key),token

    def update(self,key,**values):
        allowed={'cookies','csrf','attempt','phase','busy','held','quote_id','publishable_key'}
        if not values or not set(values)<=allowed:
            raise ValueError('Invalid session update')
        with self.db() as db:
            db.execute('UPDATE api_sessions SET '+','.join(k+'=?' for k in values)+' WHERE id=?',(*values.values(),key))

    def authenticate(self,key,site_id,token):
        row=self.read(key)
        if not row or row['site_id']!=site_id or not hmac.compare_digest(row['token_hash'],digest(token)):
            raise HTTPException(401,'Use this checkout session’s bearer token')
        if row['expires']<=self.clock():
            raise HTTPException(410,'Checkout session access expired; contact the store about an unfinished payment')
        return row

    def lock(self,key):
        with self.lock_guard:
            lock=self.locks.get(key)
            if lock is None:
                lock=threading.Lock();self.locks[key]=lock
            return lock

    def claim(self,key,operation):
        with self.db() as db:
            result=db.execute('UPDATE api_sessions SET busy=? WHERE id=? AND busy IS NULL AND held IS NULL',(operation,key))
            if result.rowcount!=1:
                raise HTTPException(409,'Payment is already processing or needs review. Check session status.')


class UpstreamError(Exception):
    def __init__(self,status=None,detail='The checkout service did not return a confirmed result'):
        self.status=status;self.detail=detail

class CsrfParser(HTMLParser):
    def __init__(self):
        super().__init__();self.token=None
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='meta' and attrs.get('name')=='checkout-csrf':self.token=attrs.get('content')


class CheckoutTransport:
    """Bounded, exclusive-use TLS connections; checkout cookies stay on each row.

    A failed request is never retried, including on a previously healthy socket.
    Financial callers therefore retain their existing uncertain-result handling.
    """
    def __init__(self,upstream=PUBLIC_UPSTREAM,*,max_connections=8,idle_timeout=4.0,timeout=90.0):
        if upstream != PUBLIC_UPSTREAM:
            raise ValueError('Unexpected checkout upstream')
        if max_connections<1 or idle_timeout<=0 or timeout<=0:
            raise ValueError('Invalid checkout connection pool settings')
        self.upstream=upstream
        self._host=parse.urlsplit(upstream).hostname
        self._context=ssl.create_default_context()
        self._max_connections=max_connections;self._idle_timeout=idle_timeout;self._timeout=timeout
        self._condition=threading.Condition();self._idle=[];self._count=0;self._closed=False

    def _acquire(self):
        deadline=time.monotonic()+self._timeout
        with self._condition:
            while True:
                if self._closed:raise UpstreamError()
                while self._idle:
                    connection,returned_at=self._idle.pop()
                    if time.monotonic()-returned_at<self._idle_timeout:
                        return connection
                    connection.close();self._count-=1
                if self._count<self._max_connections:
                    # Construction does not perform network I/O. The first request
                    # connects using the system trust store and hostname checking.
                    connection=http.client.HTTPSConnection(self._host,timeout=self._timeout,context=self._context)
                    self._count+=1
                    return connection
                remaining=deadline-time.monotonic()
                if remaining<=0:raise UpstreamError()
                self._condition.wait(remaining)

    def _release(self,connection,reusable):
        with self._condition:
            if reusable and not self._closed:
                self._idle.append((connection,time.monotonic()))
            else:
                connection.close();self._count-=1
            self._condition.notify()

    def close(self):
        with self._condition:
            self._closed=True
            for connection,_ in self._idle:connection.close()
            self._count-=len(self._idle);self._idle.clear();self._condition.notify_all()

    def call(self,row,method,path,body=None,client_ip=None):
        # Paths and link IDs come only from the server's published catalog.
        if not re.fullmatch(r'/c/choice-[a-f0-9]{32}|/api/(?:start-checkout|config|status|quote|authorize|resume|capture)',path):
            raise ValueError('Unexpected checkout path')
        target=path
        if path.startswith('/api/'):
            target+='?'+parse.urlencode({'link_id':row['link_id']})
        cookies=json.loads(row['cookies'])
        if any(not (k=='__Host-checkout-browser' or re.fullmatch(r'purchase_[a-f0-9]{20}',k)) for k in cookies):
            raise ValueError('Unexpected upstream cookie')
        headers={'Accept':'application/json','Host':parse.urlsplit(PUBLIC_UPSTREAM).netloc,
            'Cookie':'; '.join(k+'='+v for k,v in cookies.items())}
        if row['attempt']:headers['X-Checkout-Attempt']=row['attempt']
        if method=='POST':
            headers.update({'Content-Type':'application/json','Origin':PUBLIC_UPSTREAM,'X-CSRF-Token':row['csrf']})
        # Do not forward/spoof a customer IP through the public Fly proxy.
        # The unchanged engine attributes these calls to this API service.
        encoded=json.dumps(body).encode() if body is not None else None
        connection=None;reusable=False
        try:
            connection=self._acquire()
            connection.request(method,target,body=encoded,headers=headers)
            response=connection.getresponse()
            raw=response.read()  # Drain completely before another session uses the socket.
            reusable=not response.will_close
            if response.status in (301,302,303,307,308):
                raise UpstreamError(detail='Unexpected checkout service redirect')
            if not 200<=response.status<300:
                try:
                    detail=json.loads(raw).get('detail')
                    if not isinstance(detail,str):detail='Checkout request was rejected'
                except (ValueError,AttributeError):detail='Checkout request was rejected'
                raise UpstreamError(response.status,detail)
            for value in response.headers.get_all('Set-Cookie',[]):
                parsed=SimpleCookie();parsed.load(value)
                for name,morsel in parsed.items():
                    if name=='__Host-checkout-browser' or re.fullmatch(r'purchase_[a-f0-9]{20}',name):
                        cookies[name]=morsel.value
        except (http.client.HTTPException,TimeoutError,OSError,ValueError):
            reusable=False
            raise UpstreamError() from None
        finally:
            if connection is not None:self._release(connection,reusable)
        try:
            data=raw.decode() if path.startswith('/c/') else json.loads(raw)
        except (ValueError,UnicodeError):raise UpstreamError() from None
        return data,cookies


def terms(q):
    o=q['option'];total=f"{q['amount']/100:.2f} {q['currency'].upper()}"
    if o.get('prepaidCycles'):
        return f"Pay {total} upfront. {o['prepaidCycles']} prepaid cycles, {o['days']} days apart. "+(f"Full plan renews every {o['renewalDays']} days." if o.get('renewal') else 'No automatic renewal.')
    return f"Pay {total} today. "+(f"Renews every {o['days']} days." if o['recurring'] else 'One-time payment. No automatic renewal.')


def install_session_api(app,site_check,catalog_loader,store,transport,origin,allowed_origins=(),clock=time.monotonic):
    router=APIRouter(prefix='/api/v1/sites/{site_id}/sessions',tags=['On-page checkout API'])
    bearer=HTTPBearer(auto_error=False,scheme_name='CheckoutSession',description='Paste the session_token from POST sessions. This is scoped to one customer checkout, not an account key.')
    display_configuration=DisplayConfigurationCache(clock=clock)

    def ready():
        if store is None:raise HTTPException(503,'Checkout session storage is not configured')

    def origin_check(req):
        if '*' not in allowed_origins and req.headers.get('origin') not in (None,origin,*allowed_origins):
            raise HTTPException(403,'Frontend origin is not registered')

    def auth(site_id,session_id,req,credentials):
        ready();site_check(site_id);origin_check(req)
        if not credentials or credentials.scheme.lower()!='bearer':
            raise HTTPException(401,'Use the checkout session_token as a Bearer token')
        return store.authenticate(session_id,site_id,credentials.credentials)

    def call(row,method,path,body=None,req=None):
        ip=req.headers.get('fly-client-ip') if req else None
        data,cookies=transport.call(row,method,path,body,ip)
        if cookies!=json.loads(row['cookies']):
            store.update(row['id'],cookies=json.dumps(cookies));row['cookies']=json.dumps(cookies)
        return data

    def upstream_status(row,req):
        return call(row,'GET','/api/status',req=req)

    def status_result(row,value):
        held=row['held']
        if value['status']=='captured':
            store.update(row['id'],phase='captured',held=None,busy=None)
            held=None
        return SessionStatus(session_id=row['id'],plan_id=row['plan_id'],
            status='needs_review' if held else value['status'],amount=value.get('amount'),currency=value.get('currency'),
            payment_intent_id=value.get('intentId'),order_id=value.get('orderId'))

    def translated(exc):
        return HTTPException(exc.status if exc.status in (400,401,403,404,409,410,422,429) else 502,exc.detail)

    def payment_result(row,value,cfg):
        secret=value.get('clientSecret','');intent=value.get('intentId','')
        if not re.fullmatch(r'pi_[A-Za-z0-9]+_secret_[A-Za-z0-9]+',secret) or secret.split('_secret_')[0]!=intent:
            raise UpstreamError(detail='The payment setup needs review')
        if not isinstance(cfg,str) or not cfg.startswith(('pk_live_','pk_test_')) or type(value.get('amount')) is not int or value['amount']<=0 or not re.fullmatch(r'[a-z]{3}',str(value.get('currency',''))):
            raise UpstreamError(detail='The payment setup needs review')
        return PaymentResult(payment_intent_id=intent,client_secret=secret,publishable_key=cfg,
            amount=value['amount'],currency=value['currency'])

    @router.post('',response_model=SessionCreated,status_code=201,summary='Start a checkout in your own frontend')
    def create(site_id:str,body:CreateSession,req:Request):
        """Returns a session ID/token, not a hosted checkout URL. Save these before sending quote/payment requests. No charge or payment authorization is created."""
        ready();site_check(site_id);origin_check(req)
        _,routes=catalog_loader(site_id)
        target=routes.get(body.plan_id)
        if not target:raise HTTPException(404,'Plan not found')
        url=parse.urlsplit(target);selection=parse.parse_qs(url.query).get('selection',[])
        if url.scheme+'://'+url.netloc!=PUBLIC_UPSTREAM or not re.fullmatch(r'/c/choice-[a-f0-9]{32}',url.path) or len(selection)!=1:
            raise HTTPException(503,'Published checkout mapping needs review')
        row,token=store.create(site_id,body.plan_id,url.path.split('/')[-1],selection[0])
        try:
            html=call(row,'GET',url.path,req=req);parser=CsrfParser();parser.feed(html)
            if not parser.token or not re.fullmatch(r'[a-f0-9]{64}',parser.token):raise UpstreamError(detail='Public checkout initialization failed')
            store.update(row['id'],csrf=parser.token);row['csrf']=parser.token
            visit=call(row,'POST','/api/start-checkout',{},req)
            if visit.get('status')!='new' or not re.fullmatch(r'[A-Za-z0-9_-]{24,100}',visit.get('attemptId','')):
                raise UpstreamError(detail='A fresh checkout attempt could not be verified')
            store.update(row['id'],attempt=visit['attemptId'],phase='new')
        except UpstreamError as exc:
            store.update(row['id'],phase='initialization_failed')
            raise translated(exc)
        return SessionCreated(session_id=row['id'],session_token=token,expires_at=int(row['expires']),plan_id=row['plan_id'],status='new')

    @router.get('/{session_id}',response_model=SessionStatus,summary='Read this checkout’s payment status')
    def status(site_id:str,session_id:str,req:Request,credentials:HTTPAuthorizationCredentials|None=Security(bearer)):
        row=auth(site_id,session_id,req,credentials)
        try:return status_result(row,upstream_status(row,req))
        except UpstreamError as exc:raise translated(exc)

    @router.get('/{session_id}/configuration',response_model=Configuration,summary='Load public Stripe configuration and allowed address/shipping choices')
    def configuration(site_id:str,session_id:str,req:Request,credentials:HTTPAuthorizationCredentials|None=Security(bearer)):
        row=auth(site_id,session_id,req,credentials)
        def load():
            cfg=call(row,'GET','/api/config',req=req)
            option=next((o for o in cfg['options'] if o['key']==row['selection']),None)
            if not cfg['ready'] or not option or option.get('blockedReason'):
                raise HTTPException(409,'This plan is not currently available for payment')
            # No upstream CSRF, purchase cookies, customer data or account secrets.
            public_option={k:option[k] for k in ('recurring','days','basePrice','prepaidCycles','upfrontPrice','renewal','renewalDays','shippable') if k in option}
            return Configuration(publishable_key=cfg['publishableKey'],currency=cfg['currency'],countries=cfg['countries'],shipping=cfg['shipping'],plan=public_option,payment_test_only=cfg.get('paymentTestOnly',False),dollar_test_available=cfg.get('dollarTestAvailable',False))
        try:
            value=display_configuration.get((row['link_id'],row['selection']),load,lambda:upstream_status(row,req))
        except UpstreamError as exc:raise translated(exc)
        store.update(row['id'],publishable_key=value.publishable_key)
        return value

    @router.post('/{session_id}/quote',response_model=QuoteResult,summary='Calculate the customer’s exact total')
    def quote(site_id:str,session_id:str,body:QuoteBody,req:Request,credentials:HTTPAuthorizationCredentials|None=Security(bearer)):
        row=auth(site_id,session_id,req,credentials)
        with store.lock(row['id']):
            row=store.read(row['id'])
            if row['held'] or row['busy']:raise HTTPException(409,'Payment needs review before changing this checkout')
            contact=body.contact.model_dump()
            if contact['country']=='US' and contact['region'] not in US_REGIONS:
                raise HTTPException(422,'Use the two-letter US state code')
            try:value=call(row,'POST','/api/quote',{'contact':contact,'selection':row['selection'],'shipping_id':body.shipping_id,**({'dollar_test':True} if body.dollar_test else {})},req)
            except UpstreamError as exc:raise translated(exc)
            store.update(row['id'],quote_id=value['id'],phase='quoted')
            o=value['option'];consent=bool(o['recurring'])
            return QuoteResult(quote_id=value['id'],amount=value['amount'],currency=value['currency'],payment_terms=terms(value),terms_consent_required=consent)

    @router.post('/{session_id}/payment',response_model=PaymentResult,summary='Prepare the Stripe Payment Element for this reviewed quote')
    def payment(site_id:str,session_id:str,body:PaymentBody,req:Request,credentials:HTTPAuthorizationCredentials|None=Security(bearer)):
        """After showing the quote and collecting any required recurring consent, call once. Return the checkout-scoped client_secret to your browser to mount Stripe Payment Element. Never send card numbers to this API. No account secret key is returned."""
        row=auth(site_id,session_id,req,credentials)
        with store.lock(row['id']):
            row=store.read(row['id'])
            if row['quote_id']!=body.quote_id:raise HTTPException(409,'Review a current quote')
            if not row['publishable_key']:raise HTTPException(409,'Load session configuration first')
            store.claim(row['id'],'authorize')
            try:
                # Return the public key for the exact current payment route. A
                # route change after quoting is still rejected by the engine.
                # These independent reads can overlap; neither a new intent nor
                # a resume may start until both replies have been verified.
                with ThreadPoolExecutor(max_workers=2) as reads:
                    config_future=reads.submit(call,dict(row),'GET','/api/config',None,req)
                    status_future=reads.submit(upstream_status,dict(row),req)
                    cfg=config_future.result()
                    current=status_future.result()
                if not cfg['ready']:raise UpstreamError(409,'The payment route is unavailable')
                public_key=cfg['publishableKey']
                row=store.read(row['id'])
                if current['status']=='awaiting_card':
                    value=call(row,'POST','/api/resume',{},req)
                else:
                    value=call(row,'POST','/api/authorize',{'quote_id':body.quote_id,'recurring_consent':body.accept_terms},req)
                result=payment_result(row,value,public_key)
            except UpstreamError as exc:
                definite=exc.status in (400,401,403,404,409,410,422,429)
                store.update(row['id'],busy=None,held=None if definite else 'authorization_unknown')
                raise translated(exc)
            store.update(row['id'],phase='awaiting_card',publishable_key=public_key,busy=None)
            return result

    @router.post('/{session_id}/resume',response_model=PaymentResult,summary='Resume the same prepared payment after refresh or a declined card')
    def resume(site_id:str,session_id:str,body:Empty,req:Request,credentials:HTTPAuthorizationCredentials|None=Security(bearer)):
        row=auth(site_id,session_id,req,credentials)
        with store.lock(row['id']):
            row=store.read(row['id'])
            if row['held']=='capture_unknown' or row['busy']:raise HTTPException(409,'Check payment status; its result needs review')
            try:
                cfg=call(row,'GET','/api/config',req=req)
                value=call(row,'POST','/api/resume',{},req)
                result=payment_result(row,value,cfg['publishableKey'])
            except UpstreamError as exc:raise translated(exc)
            store.update(row['id'],phase='awaiting_card',publishable_key=cfg['publishableKey'],held=None)
            return result

    @router.post('/{session_id}/complete',response_model=SessionStatus,summary='Finish the Sticky order after Stripe confirms authorization')
    def complete(site_id:str,session_id:str,body:CompleteBody,req:Request,credentials:HTTPAuthorizationCredentials|None=Security(bearer)):
        """Call only after Stripe confirms this PaymentIntent with status requires_capture. The intent ID must match this session. The payment engine rechecks price/configuration, captures through Sticky and verifies order read-back. Only status=captured is a completed order. Repeated successful completion returns the same receipt; uncertain results stay held."""
        row=auth(site_id,session_id,req,credentials)
        with store.lock(row['id']):
            row=store.read(row['id'])
            try:value=upstream_status(row,req)
            except UpstreamError as exc:raise translated(exc)
            if value.get('intentId')!=body.payment_intent_id:
                raise HTTPException(409,'Payment intent does not belong to this checkout')
            if value['status']=='captured':return status_result(row,value)
            if value['status']!='awaiting_card':raise HTTPException(409,'Payment is not ready to complete; check its status')
            store.claim(row['id'],'capture')
            try:
                call(row,'POST','/api/capture',{},req)
                value=upstream_status(row,req)
                if value['status']!='captured':raise UpstreamError(detail='Order result needs review')
            except UpstreamError as exc:
                # Capture errors can follow an authorization. Never retry blindly.
                store.update(row['id'],busy=None,held='capture_unknown')
                raise translated(exc)
            store.update(row['id'],phase='captured',busy=None,held=None)
            return status_result(store.read(row['id']),value)

    @router.post('/{session_id}/portal',response_model=PortalEnrollmentResult,summary='Open the member portal for this completed checkout')
    def portal(site_id:str,session_id:str,body:Empty,req:Request,credentials:HTTPAuthorizationCredentials|None=Security(bearer)):
        row=auth(site_id,session_id,req,credentials)
        expected=(site_check(site_id) or {}).get('portal_site')
        if not expected:
            try:expected=catalog_loader(site_id)[0]._portal_site
            except Exception:expected=None  # the engine still binds the invitation to the order's own site
        with store.lock(row['id']):
            try:
                current=upstream_status(row,req)
                if current['status']!='captured':
                    raise HTTPException(409,'Complete the checkout before creating a member account')
                result=call(row,'POST','/api/portal-enrollment',{},req)
                url=parse.urlsplit(result.get('enrollment_url',''))
                upstream=parse.urlsplit(getattr(transport,'upstream',PUBLIC_UPSTREAM))
                if url.scheme!='https' or url.netloc!=upstream.netloc or not url.path.startswith('/portal/') or url.username or url.password:
                    raise UpstreamError(detail='The member portal link could not be verified')
                portal_site=result.get('site_id','')
                # A checkout for one brand must never hand back another brand's portal.
                if url.path.split('/')[2:3]!=[portal_site] or (expected and portal_site!=expected):
                    raise UpstreamError(detail='The member portal link belongs to another site')
                return PortalEnrollmentResult(site_id=site_id,portal_site_id=portal_site,enrollment_url=result['enrollment_url'],expires_at=result.get('expires_at'))
            except UpstreamError as exc:raise translated(exc)

    app.include_router(router)
