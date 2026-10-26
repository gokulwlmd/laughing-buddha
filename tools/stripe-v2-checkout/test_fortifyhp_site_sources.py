import copy
import unittest
from types import SimpleNamespace
from ops.fortifyhp_site_sources import source_records
from plans import choice_id
from sites import checkout_id


class CanonicalSiteSourcesTests(unittest.TestCase):
    def fixture(self):
        data = {}
        manifest = {'version': 1, 'sites': [{'site_id': 'fortifyhp', 'therapies': []}]}
        for n in range(10):
            sid, tid, sku = 'source-' + str(n), 'template-' + str(n), 'SKU' + str(n)
            data['plan_checkout', sid] = dict(id=sid, site_id='fortifyhp', campaign_id=195,
                template_id=tid, entries=[dict(sku=sku, purchase_option_id='term', options=['1:2:3'])])
            cid = choice_id(sid, sku, 'term')
            data['link', cid] = dict(id=cid, plan_checkout_id=sid, options=['1:2:3'])
            manifest['sites'][0]['therapies'].append(dict(source_plan_id=sid,
                published_plan_id='site-api-fortifyhp-catalog-' + str(n)))
        return data, manifest, SimpleNamespace(get=lambda k, i: data.get((k, i)))

    def test_canonical_mapping_preserves_old_sources_and_replays(self):
        data, manifest, admin = self.fixture()
        before = copy.deepcopy(manifest)
        rows, replacement = source_records(admin, manifest)
        self.assertEqual(manifest, before)
        self.assertEqual(len(rows), 20)
        for kind, key, value in rows:
            data[kind, key] = value
        again, final = source_records(admin, replacement)
        self.assertEqual((again, final), (rows, replacement))
        for n, therapy in enumerate(final['sites'][0]['therapies']):
            self.assertEqual(therapy['source_plan_id'], checkout_id('fortifyhp', 'template-' + str(n)))
            self.assertIn(('plan_checkout', 'source-' + str(n)), data)

    def test_missing_child_or_wrong_site_blocks(self):
        data, manifest, admin = self.fixture()
        data['plan_checkout', 'source-0']['site_id'] = 'other'
        with self.assertRaises(ValueError):
            source_records(admin, manifest)
        data['plan_checkout', 'source-0']['site_id'] = 'fortifyhp'
        del data['link', choice_id('source-0', 'SKU0', 'term')]
        with self.assertRaises(ValueError):
            source_records(admin, manifest)
