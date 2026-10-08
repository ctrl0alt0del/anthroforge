"""Persistent intent, transactional errors and native region policy qualification."""
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4
import ctypes as C
import unittest
from unittest.mock import patch
import numpy as np
from core.muscle_relationships import store, migration, fingerprints, reconcile, policy, changes, importing
from core.muscle_relationships.identity import pair_id, token
from core.muscle_relationships.native import PolicyInput, PolicyInputV2
from core.muscle_stacking.native import NativeStackEngine
from pair_fixture_adapter import wait
from stack_multi_fixtures import settings
from test_muscle_stacking import inflated
from relationship_fixtures import fixture, cases


def evaluate(engine, domains, config, generation=1, document=None):
    stamp = fingerprints.manifest(domains, config)
    if document: config = replace(config, relationships=policy.capture(document, stamp, domains))
    engine.submit(domains, config, generation); result = wait(engine)
    return result, {key.muscle: v for key, v in engine.surfaces().items()}, stamp


def initial():
    root = {}; document = migration.ensure(root)
    domains = [inflated('a', 0, .3, n=9), inflated('b', .1, .4, n=9)]
    with NativeStackEngine() as engine: result, _, stamp = evaluate(engine, domains, settings())
    document = reconcile.reconcile(document, stamp, result)
    with store.transaction(root, document, 0): pass
    return root, store.read(root), domains, stamp


def comparison(test, first, second):
    def normalized(result):
        return sorted((tuple(sorted((p['first']['muscle'], p['second']['muscle']))), p['order']['status']) for p in result['pairs'])
    test.assertEqual(normalized(first[0]), normalized(second[0]))
    test.assertEqual(first[0]['stacking']['status'], second[0]['stacking']['status'])
    for key in first[1]: np.testing.assert_allclose(first[1][key], second[1][key], atol=2e-6, rtol=0)


class RelationshipTests(unittest.TestCase):
    def test_schema_one_requests_never_become_explicit(self):
        value = deepcopy(self.document); value['schema'] = 1
        row = value['records'][self.identity]; row['intent'] = dict(cover=row['covering'])
        self.root[store.KEY] = store.encode(value)
        upgraded = migration.ensure(self.root)
        self.assertEqual(upgraded['schema'], 2)
        self.assertEqual(upgraded['records'][self.identity]['intent']['mode'], 'requested')

    def test_explicit_intent_survives_import_but_not_stale_evidence(self):
        row = self.document['records'][self.identity]; row['intent'] = dict(cover=row['covering'], mode='explicit')
        mapping = {tuple(k): ('copy_'+k[0], k[1], k[2]) for k in row['pair']}
        imported = importing.remap(self.document, str(uuid4()), mapping)
        new = next(iter(imported['records'].values()))
        self.assertEqual(new['intent']['mode'], 'explicit'); self.assertNotIn('effective_order', new)
        row['effective_order'] = dict(status='supported')
        absent = reconcile.reconcile(self.document, self.stamp, dict(pairs=[]))
        self.assertNotEqual(absent['records'][self.identity]['state'], 'active')

    def setUp(self):
        self.root, self.document, self.domains, self.stamp = initial()
        self.identity = next(iter(self.document['records']))

    def test_stable_id_and_serialization(self):
        row = self.document['records'][self.identity]
        self.assertEqual(pair_id(self.document['namespace'], row['pair'][::-1]), self.identity)
        self.assertEqual(store.decode(store.encode(self.document)), self.document)

    def test_store_rollback_and_stale_revision(self):
        before = dict(self.root)
        with self.assertRaises(RuntimeError):
            with store.transaction(self.root, self.document, self.document['revision']): raise RuntimeError('injected')
        self.assertEqual(self.root, before)
        with self.assertRaises(ValueError):
            with store.transaction(self.root, self.document, 0): pass

    def test_bad_schema_and_checksum_preserve_data(self):
        before = dict(self.root); value = deepcopy(self.document); value['schema'] = 77
        with self.assertRaises(ValueError): store.encode(value)
        with self.assertRaises(ValueError): store.decode(self.root[store.KEY].replace('checksum', 'broken'))
        self.assertEqual(self.root, before)

    def test_exclusion_survives_disappearance(self):
        row = self.document['records'][self.identity]; row['intent']['excluded'] = True
        absent = reconcile.reconcile(self.document, self.stamp, dict(pairs=[]))
        with NativeStackEngine() as engine: result, out, _ = evaluate(engine, self.domains, settings(), document=absent)
        self.assertEqual(result['pairs'][0]['policy']['status'], 'excluded')
        self.assertEqual(result['pairs'][0]['order']['status'], 'supported')
        np.testing.assert_array_equal(out['b'], self.domains[1].own)

    def test_requested_order_cannot_reverse_geometry(self):
        row = self.document['records'][self.identity]; row['intent']['cover'] = row['underlying']
        with NativeStackEngine() as engine: result, out, _ = evaluate(engine, self.domains, settings(), document=self.document)
        self.assertEqual(result['pairs'][0]['order']['status'], 'supported')
        self.assertEqual(result['pairs'][0]['policy']['status'], 'manual_order_conflict')
        self.assertEqual(result['stacking']['status'], 'incomplete'); np.testing.assert_array_equal(out['b'], self.domains[1].own)
        row['intent']['cover'] = row['covering']
        with NativeStackEngine() as engine: self.assertEqual(evaluate(engine, self.domains, settings(), document=self.document)[0]['stacking']['status'], 'complete')

    def test_region_and_clear_warm_match_fresh(self):
        cover = self.domains[1]; keep = np.mean(cover.base[cover.faces, 0], axis=1) < 0
        faces = [[int(p), int(s)] for p, s in zip(cover.parts[keep], cover.sources[keep])]
        document = changes.apply(self.document, [dict(id=self.identity, region=faces)], self.stamp, self.domains)
        with NativeStackEngine() as warm, NativeStackEngine() as fresh:
            evaluate(warm, self.domains, settings()); a = evaluate(warm, self.domains, settings(), 2, document)
            b = evaluate(fresh, self.domains, settings(), document=document); comparison(self, a, b)
            bonus = a[1]['b'][:, 2] - cover.own[:, 2]
            self.assertGreaterEqual(bonus[cover.base[:, 0] < -.5].min(), .2-2e-6)
            self.assertLess(bonus[cover.base[:, 0] > .75].max(), .1)
            cleared = changes.apply(document, [dict(id=self.identity, region=None)], self.stamp, self.domains)
            c = evaluate(warm, self.domains, settings(), 3, cleared); self.assertGreater(c[1]['b'][-1, 2], a[1]['b'][-1, 2])

    def test_topology_version_and_unknown_face(self):
        document = changes.apply(self.document, [dict(id=self.identity, region=[[0, 0]])], self.stamp, self.domains)
        stamp = dict(self.stamp, version='changed')
        self.assertEqual(reconcile.intent_status(document['records'][self.identity]['intent'], stamp), 'selection_algorithm_changed')
        edited = [self.domains[0], replace(self.domains[1], sources=self.domains[1].sources+10)]
        with NativeStackEngine() as engine:
            result = evaluate(engine, edited, settings(), document=document)[0]
            self.assertEqual(result['pairs'][0]['policy']['status'], 'stale_selected_region')
        with self.assertRaises(ValueError): changes.apply(document, [dict(id=self.identity, region=[[999, 999]])], self.stamp, self.domains)

    def test_content_not_claimed_revision(self):
        relabeled = [replace(d, revision='unrelated-label') for d in self.domains]
        self.assertEqual(self.stamp, fingerprints.manifest(relabeled, settings()))
        edited = [replace(self.domains[0], own=self.domains[0].own+.01), self.domains[1]]
        self.assertTrue(fingerprints.changed(self.stamp, fingerprints.manifest(edited, settings())))

    def test_import_remap_and_missing_ids(self):
        row = self.document['records'][self.identity]; mapping = {tuple(k): ('new_'+k[0], k[1], k[2]) for k in row['pair']}
        value = importing.remap(self.document, str(uuid4()), mapping)
        self.assertNotIn(self.identity, value['records']); store.encode(value)
        missing = importing.remap(self.document, str(uuid4()), {})
        self.assertTrue(next(iter(missing['records'].values()))['unresolved_import'])
        with self.assertRaises(ValueError): importing.remap(self.document, str(uuid4()), {tuple(k): ('same', 'source', 'A') for k in row['pair']})

    def test_legacy_migration(self):
        import json
        pair = self.document['records'][self.identity]['pair']; root = {migration.CONFIG: json.dumps(dict(exclusions=[pair]))}
        document = migration.ensure(root)
        self.assertEqual(migration.exclusions(document), [pair]); self.assertNotIn('exclusions', json.loads(root[migration.CONFIG]))

    def test_descendants_and_settings_roundtrip(self):
        records = [dict(underlying=['a', 'source', 'A'], covering=['b', 'source', 'A']), dict(underlying=['b', 'source', 'A'], covering=['c', 'source', 'A'])]
        self.assertEqual(len(fingerprints.affected({token(records[0]['underlying']): ['own']}, dict(enumerate(records)))), 3)
        self.assertEqual(self.stamp, store.decode(store.encode(self.document))['manifest'])

    def test_bad_intent_submission_keeps_prior_result(self):
        from core.muscle_relationships import native
        with NativeStackEngine() as engine:
            evaluate(engine, self.domains, settings()); before = engine.summary()
            with patch.object(native, 'arrays', return_value=((PolicyInputV2*1)(PolicyInputV2(PolicyInput(1, 1, 0, 0, 0, 0, 0), 0)), (C.c_int64*0)())):
                with self.assertRaises(ValueError): engine.submit(self.domains, settings(), 2)
            self.assertEqual(engine.summary()['generation'], before['generation'])


class IncrementalMatrix(unittest.TestCase):
    def test_all_sixteen_changes(self):
        for name, domains, config in cases():
            with self.subTest(case=name), NativeStackEngine() as warm, NativeStackEngine() as fresh:
                evaluate(warm, fixture(), settings()); a = evaluate(warm, domains, config, 2)
                if name == 'eviction': a = evaluate(warm, domains, config, 3)
                comparison(self, a, evaluate(fresh, domains, config))


class PolicyRepresentations(unittest.TestCase):
    def test_mirror_sides_and_branch_provenance(self):
        for instance, side in [('source', 'A'), ('mirror', 'A'), ('source', 'B'), ('mirror', 'B')]:
            with self.subTest(instance=instance, side=side):
                values = [inflated('a', 0, .3), inflated('b', .1, .4)]
                values = [replace(d, key=replace(d.key, instance=instance, side=side), parts=np.arange(len(d.faces))%3) for d in values]
                with NativeStackEngine() as engine:
                    result, _, stamp = evaluate(engine, values, settings())
                    document = reconcile.reconcile(store.empty(str(uuid4())), stamp, result); identity = next(iter(document['records']))
                    faces = sorted({(int(p), int(s)) for p, s in zip(values[1].parts, values[1].sources)})
                    document = changes.apply(document, [dict(id=identity, region=[list(f) for f in faces])], stamp, values)
                    result, output, _ = evaluate(engine, values, settings(), 2, document)
                    self.assertEqual(result['stacking']['status'], 'complete'); np.testing.assert_allclose(output['b'][:, 2], .7, atol=2e-6)

    def test_cropped_material_selection(self):
        from test_muscle_pairs_fields import evaluate as field, FieldTests
        _, _, captured = field(FieldTests().spec(), output_domain=dict(normal=(1, 0, 0), offset=.43, keep_positive=True))
        cover = captured[0]; provider = replace(cover, key=replace(cover.key, muscle='provider'), group='provider', base=cover.base-cover.direction*.1)
        provider = replace(provider, own=provider.base+provider.direction*.2)
        with NativeStackEngine() as engine:
            result, _, stamp = evaluate(engine, [provider, cover], settings())
            document = reconcile.reconcile(store.empty(str(uuid4())), stamp, result); identity = next(iter(document['records']))
            faces = sorted({(int(p), int(s)) for p, s in zip(cover.parts, cover.sources)})
            document = changes.apply(document, [dict(id=identity, cover=list((cover.key.muscle, cover.key.instance, cover.key.side)), region=[list(f) for f in faces])], stamp, [provider, cover])
            result, _, _ = evaluate(engine, [provider, cover], settings(), 2, document)
            self.assertEqual(result['pairs'][0]['policy']['status'], 'allowed')
