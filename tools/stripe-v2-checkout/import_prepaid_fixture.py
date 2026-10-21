"""Import the user-authorized, already-created synthetic prepaid setup.

Run once on the existing Fly volume after deploying prepaid support. It creates no
owner/session and performs no Sticky writes. Existing configuration is never replaced.
The test master is excluded from bulk assignment to future campaigns by default.
"""
import json,time
from decimal import Decimal
from app import app
from master import assignment_id,fingerprint,product_contract
from prepaid import configuration,cycles_for
from catalog import resolve,quote


def run(application=None):
    admin=(application or app).state.admin;api=admin.api;sku='WLMD-PREPAY-cfef3de8';cid=422;pid=55098;oid=712;brand_id='campaign-422'
    brand=admin.get('brand',brand_id)
    assert brand and brand['campaign_id']==cid,'Original test brand missing; do not invent a mapping'
    product=api.detail(f'/api/v2/products/{pid}');offer=api.detail(f'/api/v2/offers/{oid}')
    assert product['sku']==sku and Decimal(str(product['price']))==300 and not product['is_shippable'] and not product.get('taxable')
    assert cycles_for(offer)==4 and {p['id'] for p in offer['products']}=={pid} and {m['id'] for m in offer['billing_models']}=={4}
    catalog=resolve(api,cid,sku);key=f'{oid}:{pid}:4'
    q=quote(api,catalog,key,2,{'country':'US','region':'CA','postal_code':'94105'})
    assert q['amount']==120000 and q['currency']=='usd'
    master,guards,preview,ops,local=admin.prepare_master('master',{'sku':sku,'name':'Prepaid test — 360 days, 4 shipment orders','category':'Test plans','product_id':pid,'currency':'USD','enabled':False,'offers':[{'id':'prepaid-four','name':'Pay upfront — 4 shipments every 90 days','price':'1200.00','billing_models':[4],'prepaid_cycles':4}]})
    assert not ops
    aid=assignment_id(brand_id,cid,sku);offering_id='master-'+aid+'-prepaid-four';link_id='master-'+aid
    offering={'id':offering_id,'brand_id':brand_id,'campaign_id':cid,'sku':sku,'name':master['offers'][0]['name'],'price':'1200.00','billing_models':[4],'configuration':configuration(4),'product_id':pid,'offer_id':oid}
    assignment={'id':aid,'brand_id':brand_id,'campaign_id':cid,'sku':sku,'master_revision':master['revision'],'currency':'USD','name':master['name'],'offers':[offering|{'master_offer_id':'prepaid-four'}],'link_id':link_id,'source_hash':fingerprint(product),'source_contract':product_contract(product),'billing_terms':master['billing_terms']}
    link={'id':link_id,'brand_id':brand_id,'campaign_id':cid,'sku':sku,'title':master['name'],'visibility':'private','options':[key],'enabled':True,'revision':1}
    rows=[('master',sku,master),('sku',sku,{'sku':sku,'name':master['name'],'product_id':pid}),('offering',offering_id,offering),('assignment',aid,assignment),('link',link_id,link)]
    with admin.store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        assert db.execute('SELECT count(*) FROM admin_owner').fetchone()[0]==1
        assert db.execute("SELECT status,order_id FROM checkouts WHERE id='legacy'").fetchone()==('captured','505015')
        assert not db.execute("SELECT 1 FROM checkouts WHERE sku=? AND status NOT IN ('new','captured')",(sku,)).fetchone()
        existing=[db.execute('SELECT data FROM admin_config WHERE kind=? AND id=?',(k,i)).fetchone() for k,i,_ in rows]
        if any(existing):
            assert all(existing),'Partial existing setup; reconcile without overwriting'
            assert all(json.loads(saved[0]).get('sku',sku)==sku for saved in existing)
            print(json.dumps({'already_imported':True,'sku':sku,'link_id':link_id}));return
        for kind,key,data in rows:db.execute('INSERT INTO admin_config(kind,id,data) VALUES(?,?,?)',(kind,key,json.dumps(data)))
        db.execute('CREATE TABLE IF NOT EXISTS admin_setup_runs(id TEXT PRIMARY KEY,created REAL NOT NULL,details TEXT NOT NULL)')
        db.execute('INSERT INTO admin_setup_runs VALUES(?,?,?)',('prepaid-cfef3de8',time.time(),json.dumps({'authorization':'User requested prepaid setup and selected every 90 days / 360-day plan','campaign_id':cid,'sku':sku,'product_id':pid,'offer_id':oid,'upfront_price':'1200.00','cycles':4,'renewal':False,'synthetic':True,'bulk_assignment_enabled':False,'created_records':[(k,i) for k,i,_ in rows]})))
    print(json.dumps({'imported':True,'sku':sku,'campaign_id':cid,'product_id':pid,'offer_id':oid,'private_link_id':link_id,'created_records':5,'bulk_assignment_enabled':False,'upfront_amount':q['amount'],'sticky_writes':0,'payment_writes':0,'owner_session_created':False}))

if __name__=='__main__':run()
