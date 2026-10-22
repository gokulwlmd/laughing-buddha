"""Scoped reads retain exact published payment boundaries and legacy fingerprints."""
import copy
import unittest
from catalog import CatalogError,resolve
from test_checkout import FakeSticky,SKU

class CatalogSpeedTests(unittest.TestCase):
    def test_published_choice_does_not_read_unrelated_products_or_include_other_models(self):
        api=FakeSticky();api.duplicate=True;api.recurring=True
        result=resolve(api,422,SKU,allowed_keys=['706:54537:2'])
        self.assertEqual([o['key'] for o in result['options']],['706:54537:2'])
        self.assertNotIn('/api/v2/products/54538',api.reads)
        self.assertEqual(result['catalogVersion'],2)
        before=result['fingerprint'];api.total='999.00'
        self.assertEqual(resolve(api,422,SKU,allowed_keys=['706:54537:2'])['fingerprint'],before)
    def test_product_offer_pair_must_belong_to_campaign(self):
        for key in ('999:54537:2','706:999:2','706:54537:999'):
            api=FakeSticky()
            with self.assertRaises(CatalogError):resolve(api,422,SKU,allowed_keys=[key])
            self.assertNotIn('/api/v2/products/999',api.reads)
            self.assertFalse(api.calls)
    def test_empty_or_malformed_scope_never_falls_back_to_all_choices(self):
        for keys in ([],['broken'],['1:2'],['1:2:3:4'],['0:1:2']):
            with self.assertRaises(CatalogError):resolve(FakeSticky(),422,SKU,allowed_keys=keys)
    def test_scoped_price_and_billing_drift_changes_fingerprint(self):
        api=FakeSticky();first=resolve(api,422,SKU,allowed_keys=['706:54537:2'])
        original=api.detail
        def changed(path):
            value=copy.deepcopy(original(path))
            if '/products/' in path:value['price']='3.00'
            return value
        api.detail=changed;second=resolve(api,422,SKU,allowed_keys=['706:54537:2'])
        self.assertNotEqual(first['fingerprint'],second['fingerprint'])
        self.assertEqual(second['options'][0]['basePrice'],'3.00')
    def test_unscoped_catalog_retains_all_exact_sku_matches_and_stable_fingerprint(self):
        api=FakeSticky();api.duplicate=True;api.recurring=True
        first=resolve(api,422,SKU);second=resolve(api,422,SKU)
        self.assertEqual(len(first['options']),4)
        self.assertEqual(first['fingerprint'],second['fingerprint'])
        self.assertNotIn('catalogVersion',first)

    def test_plan_prefetch_parallelizes_distinct_products_and_reuses_each_read(self):
        import threading
        from plans import ReadCache
        api=FakeSticky();api.duplicate=True;barrier=threading.Barrier(2);original=api.detail
        def detail(path):
            if '/products/' in path:barrier.wait(timeout=3)
            return original(path)
        api.detail=detail;cache=ReadCache(api)
        cache.prefetch_choices(422,{'706:54537:2','706:54538:2'})
        reads=list(api.reads)
        for pid in (54537,54538):resolve(cache,422,SKU,allowed_keys=[f'706:{pid}:2'])
        self.assertEqual(api.reads,reads)
        self.assertEqual(reads.count('/api/v2/products/54537'),1)
        self.assertEqual(reads.count('/api/v2/products/54538'),1)
    def test_plan_prefetch_never_fetches_an_unattached_product(self):
        from plans import ReadCache
        api=FakeSticky();ReadCache(api).prefetch_choices(422,{'999:999:2','706:999:2'})
        self.assertNotIn('/api/v2/products/999',api.reads)
        self.assertNotIn('/api/v2/offers/999',api.reads)
