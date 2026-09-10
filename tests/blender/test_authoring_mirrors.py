"""Native mirrored authoring stays editable and persists without duplicate entities."""
import tempfile
import json
from pathlib import Path
import bpy
import numpy as np
from _helpers import BlenderTestCase, root
from test_authoring_v04 import setup, call
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.authoring.storage import FileStore


def mirrored_document(r, folder):
    value = setup(r, folder)
    instance = next(iter(value['instances'].values()))
    instance['symmetry'] = dict(mode='native_mirror', plane_frame='/skeleton_profiles/default/frames/origin',
                                plane_axis='y', plane_coordinate=.5)
    return value


def publish(test, r, folder, value, revision=0):
    draft = call(r, folder, 'draft', value, revision, document=value)
    test.assertEqual(draft['status'], 'success', draft)
    result = call(r, folder, 'compile', value, draft['draft_revision'])
    test.assertEqual(result['status'], 'success', result)
    result = call(r, folder, 'publish', value, draft['draft_revision'])
    test.assertTrue(result['published'], result)
    return draft['draft_revision']


def check_pairs(test, r):
    objects = [o for o in bpy.context.scene.objects if o.get('af_root_name') == r.name and o.get('af_muscle_proxy')]
    for kind in ('BASE', 'INFL'):
        source = next(o for o in objects if o.get('af_muscle_surface') == kind and not o.get('af_muscle_mirror_proxy'))
        mirror = next(o for o in objects if o.get('af_muscle_surface') == kind and o.get('af_muscle_mirror_proxy'))
        test.assertEqual(source.data, mirror.data)
        expected = np.array([tuple(source.matrix_world @ v.co) for v in source.data.vertices])
        expected[:, 1] *= -1
        np.testing.assert_allclose([tuple(mirror.matrix_world @ v.co) for v in mirror.data.vertices], expected, atol=1e-6)
    test.assertEqual(len(r.af_vcp_system.muscles), 1)
    test.assertEqual(len(objects), 4)


class AuthoringMirrorTests(BlenderTestCase):
    def test_saved_native_face_bindings_republish_with_mirrors(self):
        r=root()
        with tempfile.TemporaryDirectory() as folder:
            value=mirrored_document(r,folder)
            revision=publish(self,r,folder,value)
            add_saved_bindings(r,folder,value)
            publish(self,r,folder,value,revision)
            check_pairs(self,r)

    def test_native_mirror_publish_edit_and_reload(self):
        r = root()
        with tempfile.TemporaryDirectory() as folder:
            publish(self, r, folder, mirrored_document(r, folder))
            check_pairs(self, r)
            edit_source(self, r)
            path = str(Path(folder)/'mirrored.blend')
            bpy.ops.wm.save_as_mainfile(filepath=path)
            bpy.ops.wm.open_mainfile(filepath=path)
            r = bpy.data.objects['AF_ROOT']
            StaticScene(r, bpy.context.scene).refresh()
            check_pairs(self, r)

    def test_explicit_republication_removes_generated_partners(self):
        r = root()
        with tempfile.TemporaryDirectory() as folder:
            value = mirrored_document(r, folder)
            revision = publish(self, r, folder, value)
            next(iter(value['instances'].values()))['symmetry'] = dict(mode='explicit')
            publish(self, r, folder, value, revision)
            self.assertFalse(any(o.get('af_muscle_mirror_proxy') or o.get('af_fiber_mirror_proxy') for o in bpy.context.scene.objects))
            self.assertEqual(len(r.af_vcp_system.muscles), 1)

    def test_instance_attachment_inherits_existing_scp_mirror(self):
        from anthroforge.core.visualization.mirror_rules import effective_rule_for_fiber
        from anthroforge.core.visualization.vcp_mirror_runtime import _rule_for_fiber
        r = root()
        with tempfile.TemporaryDirectory() as folder:
            value = mirrored_document(r, folder)
            publish(self, r, folder, value)
            fiber = r.af_vcp_system.fibers[0]
            inherit_plane(r, fiber)
            scps = {s.id:s for s in r.af_scp_system.scps}
            self.assertEqual(effective_rule_for_fiber(fiber, scps)[0], 'Y')
            self.assertEqual(_rule_for_fiber(fiber, {}, scps)[0], 'Y')


def inherit_plane(r, fiber):
    from anthroforge.core.scp_runtime.runtime_state import set_mirror_status, set_mirror_effective_axis
    with suppress_vcp_prop_updates():
        del fiber['af_authoring_symmetry']
        for scp in r.af_scp_system.scps:
            scp.mirror_enabled, scp.mirror_axis = True, 'Y'
            set_mirror_status(scp, 'SOURCE')
            set_mirror_effective_axis(scp, 'Y')


def add_saved_bindings(r,folder,value):
    saved=FileStore(folder).get('v04_drafts',[r['af_authoring_id'],value['document_id']])
    name,instance=next(iter(value['instances'].items()))
    stations=value['recipes'][instance['recipe'].split('/')[-1]]['construction']['stations']
    row=saved['compiled']['outputs'][name]['fibers'][0]
    fid=saved['published']['native_ids'][name]['fibers'][row['id']]
    fiber=next(f for f in r.af_vcp_system.fibers if f.id==fid)
    parameters=[fiber.a_attach_param,*[p.attach_param for p in fiber.mid_touches],fiber.b_attach_param]
    anchors=[]
    for station,anchor,raw in zip(stations,row['anchors'],parameters):
        binding={k:v for k,v in json.loads(raw).items() if k in ('tri_vidx','tri_weights')}
        anchors.append(dict(region=instance['bindings'][station['region_role']],seed=[-100]*3,offset=anchor['offset'],surface_binding=binding))
    instance['route_overrides']={row['id']:dict(anchors=anchors,evidence=instance['evidence'])}


def edit_source(test, r):
    muscle = r.af_vcp_system.muscles[0]
    source = next(o for o in bpy.context.scene.objects if o.get('af_muscle_proxy') and o.get('af_muscle_surface') == 'INFL'
                  and not o.get('af_muscle_mirror_proxy'))
    before = np.array([tuple(v.co) for v in source.data.vertices])
    with suppress_vcp_prop_updates():
        muscle.inflation_max_value *= 2
    StaticScene(r, bpy.context.scene).refresh()
    test.assertGreater(np.max(np.abs(before-np.array([tuple(v.co) for v in source.data.vertices]))), 1e-4)
    check_pairs(test, r)
