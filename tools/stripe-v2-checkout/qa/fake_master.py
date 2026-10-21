"""Synthetic master catalog support shared by regression and browser tests."""
import copy
from decimal import Decimal
from test_admin import AdminSticky
from test_checkout import FakeSticky

class MasterSticky(AdminSticky):
    def __init__(self):
        super().__init__();self.campaign_offers={};self.model_changes={};self.fail_attachment=False;self.new_campaigns={};self.deny_new_campaign=False
    def models(self):
        return [dict({'id':mid,'name':'One-time purchase' if mid==2 else str(days)+' days subscription','days':days,'type':{'id':1},'is_archived':0},**self.model_changes.get(mid,{})) for mid,days in [(2,0),(3,30),(4,90),(5,180),(7,270),(6,360)]]
    def detail(self,path):
        if path=='/api/v2/products/55098':return {'id':55098,'sku':'WLMD-PREPAY-cfef3de8','name':'Synthetic prepaid shipment','price':'300.00','category_id':10,'cost_of_goods':'0','restocking_fee':'0','max_quantity':1,'is_shippable':0,'taxable':0,'archived_flag':0}
        if path=='/api/v2/products/2856':
            return {'id':2856,'name':'Compounded Tirzepatide - 1 month supply','sku':'TIRZ-1M','price':'449.00','category_id':113,
                'cost_of_goods':'0','restocking_fee':'0','max_quantity':1,'is_shippable':1,'taxable':0,'archived_flag':0,'is_variant_enabled':0}
        if '/offers/' in path:
            if path.endswith('/706'):return FakeSticky.detail(self,'/api/v2/campaigns/422')['offers'][0]
            d=super().detail(path)
            if d.get('type_id')==2:d.update(is_prepaid=1,prepaid_profile=d.get('prepaid'),cycle_type={'id':1})
            models={m['id']:m for m in self.models()};d['billing_models']=[models[m['id']] for m in d['billing_models']];return d
        if '/campaigns/' in path:
            cid=int(path.rsplit('/',1)[1])
            if cid in self.new_campaigns and self.deny_new_campaign:raise RuntimeError('Campaign access not granted')
            d=copy.deepcopy(self.new_campaigns[cid]) if cid in self.new_campaigns else super().detail(path)
            d.setdefault('countries',[{'id':223,'iso':'US','name':'United States'}])
            for country in d['countries']:country.setdefault('id',223)
            d['offers']=[self.detail('/api/v2/offers/'+str(i)) for i in self.campaign_offers.get(cid,[706])];return d
        return super().detail(path)
    def call(self,method,path,body=None):
        if path=='/api/v2/order_total/calculate' and body['offers'][0].get('prepaid_cycles'):
            line=body['offers'][0];cycles=line['prepaid_cycles'];product=self.detail('/api/v2/products/'+str(line['product_id']));total=str(Decimal(str(product['price']))*cycles)
            self.calls.append((method,path,copy.deepcopy(body)))
            return {'status':'SUCCESS','data':{'total':total,'line_items':[{'id':product['id'],'qty':1,'is_prepaid':True,'prepaid':{'term':cycles,'total':total}}]}}
        if path=='/api/v2/billing_models':return {'status':'SUCCESS','data':self.models()}
        if method=='POST' and path=='/api/v2/campaigns':
            self.calls.append((method,path,copy.deepcopy(body)));cid=800+len(self.new_campaigns)
            self.new_campaigns[cid]=self.detail('/api/v2/campaigns/422')|{'id':cid,'name':body['name']}
            self.campaign_offers[cid]=body['offers'];return {'status':'SUCCESS','data':{'id':cid}}
        if method=='PUT' and '/campaigns/' in path:
            self.calls.append((method,path,copy.deepcopy(body)))
            if self.fail_attachment:raise RuntimeError('Uncertain attachment')
            cid=int(path.rsplit('/',1)[1]);self.campaign_offers[cid]=body['offers'];return {'status':'SUCCESS','data':{'id':cid}}
        result=super().call(method,path,body)
        if path=='/api/v1/order_view':
            line=next(b['offers'][0] for _,p,b in reversed(self.calls) if p=='/api/v1/new_order')
            if line.get('prepaid_cycles'):result['products'][0]['prepaid']=[{'total_cycles':str(line['prepaid_cycles']),'current_cycle':'1','is_renew':'0'}]
        return result
