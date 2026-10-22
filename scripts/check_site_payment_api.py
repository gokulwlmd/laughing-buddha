"""Live API smoke check: sessions/config/status and an optional synthetic quote.

Never calls payment, resume or complete; never authorizes or charges a card.
Prints no session tokens, upstream cookies, public keys or contact values.
"""
import argparse
import json
import os
from pathlib import Path
from urllib import error,request


def run(origin,quote=False,save_session=None):
    base=origin.rstrip('/')+'/api/v1/sites/payment-test/sessions'
    def call(url,body=None,token=None):
        headers={'Accept':'application/json'}
        if token:headers['Authorization']='Bearer '+token
        if body is not None:headers['Content-Type']='application/json'
        req=request.Request(url,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        with request.urlopen(req,timeout=120) as response:return response.status,json.load(response)
    code,health=call(origin.rstrip('/')+'/health')
    assert code==200 and health['session_storage_configured']
    code,session=call(base,{'plan_id':'sema-1m'})
    assert code==201 and 'checkout_url' not in session
    path=base+'/'+session['session_id'];token=session['session_token']
    code,cfg=call(path+'/configuration',token=token)
    assert code==200 and cfg['publishable_key'].startswith(('pk_live_','pk_test_'))
    code,status=call(path,token=token)
    assert code==200 and status['status']=='new' and status['payment_intent_id'] is None
    _,other=call(base,{'plan_id':'sema-1m'})
    try:
        call(base+'/'+other['session_id'],token=token)
        raise AssertionError('Cross-session token was accepted')
    except error.HTTPError as exc:assert exc.code==401
    result={'health':200,'session_created':True,'configuration':200,'session_isolation':True,'financial_calls':0}
    if quote:
        contact={'name':'API Integration Test','email':'api-smoke@example.invalid','phone':'+12025550100',
            'address':'1 Test Way','city':'San Francisco','region':'CA','postal_code':'94105','country':'US'}
        shipping=cfg['shipping'][0]['id'] if len(cfg['shipping'])==1 else None
        code,total=call(path+'/quote',{'contact':contact,'shipping_id':shipping},token)
        assert code==200 and total['amount']>0
        result.update(quote=200,amount=total['amount'],currency=total['currency'])
        _,status=call(path,token=token)
        assert status['status']=='new' and status['payment_intent_id'] is None
    if save_session:
        target=Path(save_session)
        fd=os.open(target,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
        with os.fdopen(fd,'w') as file:json.dump({'path':path,'token':token},file)
    print(json.dumps(result))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin',default='https://wlmd-site-api-demo-0f89b1bb.fly.dev')
    parser.add_argument('--quote',action='store_true',help='Calculate one draft using synthetic contact data; no payment')
    parser.add_argument('--save-session',help='Private local file for checking this test session after an API deployment')
    args=parser.parse_args();run(args.origin,args.quote,args.save_session)
