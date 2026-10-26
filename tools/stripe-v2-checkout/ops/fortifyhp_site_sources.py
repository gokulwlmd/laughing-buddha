"""Attach verified rollout sources to the admin's canonical site/template IDs.

Run on the shared Fly app after fortifyhp_rollout publish. No provider writes.
Existing source/public checkout URLs and payment records remain untouched.
"""
import copy
import fcntl
import json
import os
from pathlib import Path

from fortifyhp_rollout import Rollout, RUN
from plans import choice_id
from sites import checkout_id


def source_records(admin, manifest):
    replacement = copy.deepcopy(manifest)
    site = next(s for s in replacement['sites'] if s['site_id'] == 'fortifyhp')
    pending = []
    for therapy in site['therapies']:
        if not therapy['published_plan_id'].startswith('site-api-fortifyhp-catalog-'):
            continue
        source = admin.get('plan_checkout', therapy['source_plan_id'])
        if not source or source.get('site_id') != 'fortifyhp' or source.get('campaign_id') != 195:
            raise ValueError('Source membership changed')
        key = checkout_id('fortifyhp', source['template_id'])
        plan = dict(source, id=key)
        pending.append(('plan_checkout', key, plan))
        for entry in source['entries']:
            purchase = entry.get('purchase_option_id', '')
            child = admin.get('link', choice_id(source['id'], entry['sku'], purchase))
            if not child or child.get('plan_checkout_id') != source['id'] or child.get('options') != entry['options']:
                raise ValueError('Source choice changed')
            cid = choice_id(key, entry['sku'], purchase)
            pending.append(('link', cid, dict(child, id=cid, plan_checkout_id=key)))
        therapy['source_plan_id'] = key
    if len([1 for k, i, v in pending if k == 'plan_checkout']) != 10:
        raise ValueError('Expected the ten expanded therapy groups')
    return pending, replacement


def apply(application):
    rollout = Rollout(application)
    if not rollout.state.get('published'):
        raise ValueError('Publish and verify the approved catalog first')
    admin = rollout.admin
    path = Path('/data/site-api-publications.json')
    with path.with_suffix('.json.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        before = json.loads(path.read_text())
        pending, replacement = source_records(admin, before)
        created = 0
        with admin.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            for kind, key, value in pending:
                old = db.execute('SELECT data FROM admin_config WHERE kind=? AND id=?', (kind, key)).fetchone()
                if old and json.loads(old[0]) != value:
                    raise ValueError('Existing canonical checkout differs; preserve and review')
                if not old:
                    db.execute('INSERT INTO admin_config VALUES(?,?,?)', (kind, key, json.dumps(value)))
                    created += 1
        temp = path.with_suffix('.sources.tmp')
        temp.write_text(json.dumps(replacement, indent=2)); temp.chmod(0o600)
        owner = path.stat(); os.chown(temp, owner.st_uid, owner.st_gid); temp.replace(path)
    rollout.state['canonical_site_sources'] = {'records_created': created, 'therapies': 10}
    rollout.save()
    return dict(therapies=10, records_created=created, provider_writes=0)


if __name__ == '__main__':
    from app import app
    with (Path('/data') / (RUN + '.lock')).open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(json.dumps(apply(app)))
