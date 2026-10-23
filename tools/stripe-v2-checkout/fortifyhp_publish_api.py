"""Publish the forty verified FortifyHP choices and atomically export its API manifest.

Run only after `fortifyhp_setup apply` succeeds, in the shared application:
`python -m fortifyhp_publish_api`. No orders, payments or Sticky mutations.
"""
import json
import fcntl
import os
from pathlib import Path
import tempfile

from demo.publish import publish_site
from demo.registry import SitePublication, load_publications
from sites import checkout_id
from therapy_skeletons import all_skeletons

ORIGIN='https://wlmd-stripe-test-0f89b1bb.fly.dev'


def build_configuration(admin, source_plan_ids=None):
    site=admin.get('site','fortifyhp')
    brand=admin.get('brand','fortifyhp')
    if (not site or site.get('brand_id')!='fortifyhp' or site.get('campaign_id')!=195
            or not brand or brand.get('campaign_id')!=195):
        raise ValueError('The FortifyHP site, brand and campaign must exist first')
    skeletons=all_skeletons()
    expected_ids={checkout_id('fortifyhp','fortifyhp-'+s['therapy']['id']) for s in skeletons}
    if source_plan_ids is not None and (len(source_plan_ids)!=4 or set(source_plan_ids)!=expected_ids):
        raise ValueError('The four recorded source checkouts do not match this setup')
    therapies=[];seen=set()
    for skeleton in skeletons:
        therapy=skeleton['therapy'];source_id=checkout_id('fortifyhp','fortifyhp-'+therapy['id'])
        source=admin.get('plan_checkout',source_id)
        if (not source or source.get('site_id')!='fortifyhp' or source.get('brand_id')!='fortifyhp'
                or source.get('campaign_id')!=195 or source.get('therapy_id')!=therapy['id']
                or not source.get('enabled') or source.get('payment_test_only')):
            raise ValueError('Source checkout is not a verified FortifyHP collection')
        entries=source.get('entries',[])
        expected={product['sku'] for product in skeleton['products']}
        if len(entries)!=len(expected) or {entry.get('sku') for entry in entries}!=expected:
            raise ValueError('Every agreed one-time and renewing plan must be mapped exactly once')
        plans=[]
        for entry in entries:
            sku=entry['sku'];choices=entry.get('options',[])
            master=admin.get('master',sku)
            if sku in seen or len(choices)!=1 or not master or master.get('therapy_id')!=therapy['id'] or not master.get('enabled'):
                raise ValueError('A master SKU or selected payment choice needs review')
            seen.add(sku)
            plans.append({'sku':sku,'selection':choices[0],'purchase_option_id':entry.get('purchase_option_id','')})
        therapies.append({'therapy_id':therapy['id'],'name':therapy['name'],'source_plan_id':source_id,
            'published_plan_id':'site-api-fortifyhp-'+therapy['id'],'plans':plans})
    if len(seen)!=40:
        raise ValueError('Exactly forty FortifyHP plans are required')
    return SitePublication.model_validate({'site_id':'fortifyhp','site_name':site['name'],'brand_id':'fortifyhp',
        'campaign_id':195,'portal_site_id':'fortifyhp','color':brand['color'],'therapies':therapies})


def export_manifest(application, target=None, source_plan_ids=None):
    cfg=application.state.settings
    if cfg.public_url!=ORIGIN or cfg.synthetic:
        raise ValueError('Run only against the shared production application')
    configuration=build_configuration(application.state.admin,source_plan_ids)
    _,portal=application.state.member_portal.site('fortifyhp')
    if portal.get('id')!='fortifyhp' or portal.get('theme')!='fortifyhp':
        raise ValueError('The FortifyHP patient portal and theme must be ready first')
    target=Path(target) if target else Path(os.environ.get('SITE_API_MANIFEST',str(cfg.state_dir/'site-api-publications.json')))
    if target.parent.resolve()!=cfg.state_dir.resolve():
        raise ValueError('Keep the runtime manifest on the application volume')
    with target.with_suffix(target.suffix+'.lock').open('a+') as publication_lock:
        os.chmod(publication_lock.name,0o600)
        if os.geteuid()==0:
            owner=cfg.state_dir.stat();os.chown(publication_lock.name,owner.st_uid,owner.st_gid)
        fcntl.flock(publication_lock.fileno(),fcntl.LOCK_EX)
        old=json.loads(target.read_text()) if target.exists() else {'version':1,'sites':[]}
        existing=load_publications(old)
        if 'fortifyhp' in existing and existing['fortifyhp']!=configuration:
            raise ValueError('Existing FortifyHP API manifest differs; review before replacement')
        existing['fortifyhp']=configuration
        manifest={'version':1,'sites':[site.model_dump(mode='json') for site in existing.values()]}
        result=publish_site(application.state.admin,configuration)
        if old!=manifest:
            filename=None
            try:
                with tempfile.NamedTemporaryFile(mode='w',dir=target.parent,prefix=target.name+'.',delete=False) as output:
                    filename=Path(output.name)
                    json.dump(manifest,output,sort_keys=True,indent=2)
                    output.write('\n');output.flush();os.fsync(output.fileno())
                    os.chmod(filename,0o600)
                    if os.geteuid()==0:
                        owner=cfg.state_dir.stat();os.chown(filename,owner.st_uid,owner.st_gid)
                filename.replace(target)
            finally:
                if filename and filename.exists():filename.unlink()
    return dict(result,manifest_path=str(target),therapies=4,portal_path='/portal/fortifyhp',
        portal_theme=portal['theme'],patient_records_copied=0,payment_authorizations=0,orders_created=0)


def main():
    # Check before importing app.py, which initializes the configured store.
    if os.environ.get('CHECKOUT_PUBLIC_URL')!=ORIGIN or os.environ.get('CHECKOUT_STATE_DIR')!='/data':
        raise RuntimeError('Run inside the shared production app with its /data volume')
    from app import app
    state_path=Path('/data/fortifyhp-production-catalog-195-v1.json')
    journal=json.loads(state_path.read_text())
    published=journal.get('published') or {}
    if published.get('site_id')!='fortifyhp' or published.get('quote_checks')!=40:
        raise RuntimeError('Complete and verify the forty-product setup before publishing its APIs')
    print(json.dumps(export_manifest(app,source_plan_ids=published.get('source_plan_ids'))))


if __name__=='__main__':
    main()
