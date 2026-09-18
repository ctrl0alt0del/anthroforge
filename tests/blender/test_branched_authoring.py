from copy import deepcopy
import tempfile
import bpy
from _helpers import BlenderTestCase, root
from test_authoring_v04 import setup, call
from test_authoring_v04 import request
from anthroforge.app.authoring.api import execute
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates


def branch_document(document):
    recipe = next(iter(document['recipes'].values()))
    main = deepcopy(recipe['construction']); main['fiber_u'] = [0, 1]
    first = main['stations'][1]; first['s'] = .35
    second = deepcopy(first); second['id'], second['s'] = 'guide2', .65
    first['sample'].update(start=.1, end=.3); second['sample'].update(start=.6, end=.8)
    main['stations'].insert(2, second)
    child = deepcopy(main); child['stations'] = [deepcopy(main['stations'][0]), deepcopy(main['stations'][-1])]
    recipe['strategy'] = 'branched_loft.v1'
    recipe['construction'] = dict(kind='branched_loft', main=main, branches=dict(side=dict(
        construction=child, boundary='last', root_anchor_indices=[1, 2], width=.25, fullness=0.)))
    return document


class BranchedAuthoringTests(BlenderTestCase):
    def test_draft_compile_publish_and_restore(self):
        r = root()
        with tempfile.TemporaryDirectory() as directory:
            document = branch_document(setup(r, directory))
            drafted = call(r, directory, 'draft', document, 0, document=document)
            self.assertEqual(drafted['status'], 'success', drafted)
            compiled = call(r, directory, 'compile', document)
            self.assertEqual(compiled['status'], 'success', compiled)
            published = call(r, directory, 'publish', document)
            self.assertEqual(published['status'], 'success', published)
            self._check_native(r)
            inspected = call(r, directory, 'reconcile', document, mode='inspect')
            self.assertEqual(inspected['status'], 'success', inspected)
            self._restore(r, directory, document)

    def _restore(self, r, directory, document):
        surface = next(s for s in r.af_vcp_system.fiber_surfaces if s.construction_mode == 'BRANCHED_LOFT')
        with suppress_vcp_prop_updates():
            surface.branches[0].fullness = .12
        message = request(r, 'reconcile', document_id=document['document_id'], expected_draft_revision=1, mode='restore')
        message['request_id'] = 'restore_branch'
        restored = execute(message, r, bpy.context.scene, directory)
        self.assertEqual(restored['status'], 'success', restored)
        self.assertAlmostEqual(surface.branches[0].fullness, 0.)

    def _check_native(self, r):
        self.assertEqual(len(r.af_vcp_system.muscles), 1)
        surfaces = [s for s in r.af_vcp_system.fiber_surfaces if s.construction_mode == 'BRANCHED_LOFT']
        self.assertEqual(len(surfaces), 1)
        self.assertEqual(len(surfaces[0].branches), 1)
        self.assertEqual(len(r.af_vcp_system.fibers), 4)
