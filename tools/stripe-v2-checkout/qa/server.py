"""Loopback-only QA server. Uses a fake Sticky service; never loads payment credentials."""
import argparse
import copy
import json
import os
from pathlib import Path
import socket
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
for key in ('STICKY_API_USERNAME','STICKY_API_PASSWORD','FLY_API_TOKEN'):
    os.environ.pop(key,None)
from fastapi import Request,HTTPException
import uvicorn
from app import Settings,StickyError,create_app
from fake_master import MasterSticky
from test_checkout import FakeSticky,SKU

class QASticky(MasterSticky):
    def __init__(self):
        super().__init__();self.recurring=True;self.intents={};self.orders={};self.campaigns={};self.flags={};self.attempts=0
    def detail(self,path):
        if self.flags.get('read_failure'):raise StickyError('Sticky is temporarily unavailable. Your changes have not been applied.')
        if '/campaigns/' in path:
            campaign=int(path.rsplit('/',1)[1])
            if campaign==999:raise StickyError('This API user cannot access the selected campaign')
            c=super().detail(path)
            if campaign in self.campaigns:
                raw=self.campaigns[campaign];c['offers']=[self.detail('/api/v2/offers/'+str(i)) for i in raw['offers']]
            c['countries']=[{'id':223,'iso_2':'US','name':'United States'}];c['channel']={'id':1};c['shipping_profiles']=[{'id':2,'name':'Free shipping'}]
            return c
        if '/offers/' in path and path.endswith('/706'):
            return FakeSticky.detail(self,'/api/v2/campaigns/422')['offers'][0]
        if '/profiles/' in path:
            d=super().detail(path)
            if self.flags.get('missing_gateway'):d['account_id']=180
            return d
        return super().detail(path)
    def call(self,method,path,body=None):
        if self.flags.get('read_failure') and (method=='GET' or path.endswith('campaign_find_active')):raise StickyError('Sticky is temporarily unavailable. Your form has been preserved.')
        if path.endswith('campaign_find_active'):
            return {'response_code':'100','campaigns':{str(i):{'campaign_id':str(i),'campaign_name':name} for i,name in [(422,'Example Brand'),(167,'Second Brand')]+[(i,c['name']) for i,c in self.campaigns.items()]}}
        if path=='/api/v2/campaigns' and method=='POST':
            self.calls.append((method,path,copy.deepcopy(body)));key=80000+len(self.campaigns);self.campaigns[key]=body
            if self.flags.get('campaign_timeout'):raise StickyError('Uncertain campaign creation')
            return {'status':'SUCCESS','data':{'id':key}}
        if path=='/api/v1/authorize_payment':
            self.calls.append((method,path,copy.deepcopy(body)));self.attempts+=1
            key='pi_qa'+str(self.attempts)
            self.intents[key]={'id':key,'amount':int(round(float(body['auth_amount'])*100)),'currency':'usd','status':'requires_payment_method','confirmed':False}
            if self.flags.get('authorize_timeout'):raise StickyError('Authorization is uncertain; contact support before retrying')
            return {'response_code':'100','digitalWalletToken':key+'_secret_qaonly','transactionID':key}
        if path=='/api/v1/new_order':
            self.calls.append((method,path,copy.deepcopy(body)))
            intent=self.intents.get(body['transactionId'])
            if not intent or not intent['confirmed'] or intent['status']!='requires_capture':return {'response_code':'10800'}
            key=str(910000+len(self.orders));line=body['offers'][0]
            self.orders[key]={'response_code':'100','order_status':'2','order_total':str(intent['amount']/100),
                'campaign_id':str(body['campaignId']),'gateway_id':str(body['forceGatewayId']),
                'products':[{'product_id':str(line['product_id']),'offer':{'id':str(line['offer_id'])},'billing_model':{'id':str(line['billing_model_id'])},'product_qty':'1','is_recurring':'0' if line['billing_model_id']==2 else '1'}]}
            if line.get('prepaid_cycles'):self.orders[key]['products'][0]['prepaid']=[{'total_cycles':str(line['prepaid_cycles']),'current_cycle':'1','is_renew':str(int(bool((self.offers[line['offer_id']].get('prepaid') or {}).get('is_subscription'))))}]
            intent['status']='succeeded'
            if self.flags.get('capture_timeout'):raise StickyError('Capture result is uncertain; contact support before retrying')
            return {'response_code':'101' if self.flags.get('extra_3ds') else '100','order_id':key}
        if path=='/api/v1/order_view':
            d=copy.deepcopy(self.orders[body['order_id'][0]])
            if self.flags.get('wrong_total'):d['order_total']='999.00'
            return d
        return super().call(method,path,body)

parser=argparse.ArgumentParser();parser.add_argument('--state-dir',required=True);args=parser.parse_args()
state=Path(args.state_dir).resolve();state.mkdir(parents=True,exist_ok=True)
sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
origin=f'http://localhost:{port}'
fake=QASticky();app=create_app(Settings(public_url=origin,state_dir=state,authorization_verified=True),fake)

@app.post('/__qa/control')
def control(body:dict):
    fake.flags.update(body)
    if 'price' in body:fake.total=fake.price=str(body['price'])
    if 'duplicate_sku' in body:fake.duplicate=body['duplicate_sku']
    if 'fail_offer' in body:fake.fail_offer=body['fail_offer']
    if body.get('expire_session'):
        with app.state.store.db() as db:db.execute('UPDATE admin_sessions SET expires=0')
    if body.get('expire_quote'):
        with app.state.store.db() as db:
            for key,raw in db.execute("SELECT id,quote FROM checkouts WHERE status='new' AND quote IS NOT NULL").fetchall():
                q=json.loads(raw);q['expires']=0;db.execute('UPDATE checkouts SET quote=? WHERE id=?',(json.dumps(q),key))
    return {'ok':True}

@app.get('/__qa/state')
def metrics():
    counts={name:sum(path.endswith('/'+name) for _,path,_ in fake.calls) for name in ('authorize_payment','new_order','products','offers','campaigns')}
    with app.state.store.db() as db:
        statuses=dict(db.execute('SELECT status,count(*) FROM checkouts GROUP BY status'))
        owners=db.execute('SELECT count(*) FROM admin_owner').fetchone()[0]
    return {'authorizationStates':[[b.get('billingState'),b.get('shippingState')] for _,path,b in fake.calls if path.endswith('/authorize_payment')],'counts':counts,'orderCount':len(fake.orders),'states':statuses,'ownerCount':owners,'brands':len(app.state.admin.records('brand')),'skus':len(app.state.admin.records('sku')),'links':len(app.state.admin.records('link'))}

@app.post('/__qa/confirm')
def confirm(body:dict):
    key=body['clientSecret'].split('_secret_')[0];intent=fake.intents[key]
    if body.get('mode')=='decline':return {'error':{'message':'Your card was declined. Try another card.'}}
    intent['confirmed']=True;intent['status']='requires_capture'
    return {'paymentIntent':{k:intent[k] for k in ('id','amount','currency','status')}}

@app.get('/__qa/retrieve')
def retrieve(id:str):
    intent=fake.intents[id]
    return {'paymentIntent':{k:intent[k] for k in ('id','amount','currency','status')}}

print(json.dumps({'origin':origin,'setupPath':'/admin?setup='+app.state.admin.setup_token}),flush=True)
uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False,proxy_headers=False)).run(sockets=[sock])
