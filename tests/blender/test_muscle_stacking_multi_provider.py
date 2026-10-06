"""Real publication, load regeneration and intact attachment identities."""
from pathlib import Path
from tempfile import TemporaryDirectory
import bpy
import numpy as np
from _helpers import BlenderTestCase
from _stacking_multi_fixture import fixture, bindings
from test_muscle_stacking import refresh
from test_muscle_pairs import finish
from test_muscle_section_profile import mesh
from anthroforge.core.muscle_pairs import runtime
from anthroforge.adapters.authoring.scene import StaticScene


class MultiProviderBlender(BlenderTestCase):
    def check_layers(self, kind):
        owner, muscles = fixture(kind); before = bindings(owner)
        own = {m.id: mesh(owner, m).copy() for m in muscles}
        bases = {m.id: mesh(owner, m, 'BASE').copy() for m in muscles}
        state = refresh(owner); self.assertEqual(state['stacking']['status'], 'complete', state)
        final = {m.id: mesh(owner, m).copy() for m in muscles}
        for m in muscles: np.testing.assert_array_equal(mesh(owner, m, 'BASE'), bases[m.id])
        self.assertEqual(bindings(owner), before)
        refresh(owner)
        for m in muscles: np.testing.assert_array_equal(mesh(owner, m), final[m.id])
        name = owner.name; self.reopen(owner, muscles, final, before)
        owner = bpy.data.objects[name]; owner.af_pair_settings.stacking = False; finish()
        for m in owner.af_vcp_system.muscles: np.testing.assert_allclose(mesh(owner, m), own[m.id], atol=2e-6)

    def reopen(self, owner, muscles, final, before):
        name = owner.name; owner.af_pair_settings.automatic = True; finish()
        with TemporaryDirectory() as folder:
            path = Path(folder)/'multi.blend'; StaticScene(owner, bpy.context.scene).save_debug_copy(path)
            bpy.ops.wm.open_mainfile(filepath=str(path)); finish(); owner = bpy.data.objects[name]
            state = runtime.inspect(bpy.context.scene, owner)
            self.assertEqual(state['stacking']['status'], 'complete', state)
            self.assertEqual(bindings(owner), before)
            for m in owner.af_vcp_system.muscles: np.testing.assert_allclose(mesh(owner, m), final[m.id], atol=2e-6)
            fibers = [o for o in bpy.context.scene.objects if o.get('af_fiber_proxy') or o.get('af_fiber_mirror_proxy')]
            self.assertEqual(len(fibers), 6)
            self.assertTrue(all(not o.hide_get() and o.display_type != 'WIRE' for o in fibers))

    def test_joint_providers(self):
        self.check_layers('overlap')

    def test_serial_layers(self):
        self.check_layers('chain')
