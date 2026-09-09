"""Verify visible native output before committing an authoring transaction."""
import numpy as np
from ...core.authoring.errors import require


def verify(port, ids, outputs):
    for name, identity in ids.items():
        surface = next(s for s in port.root.af_vcp_system.fiber_surfaces if s.id == identity["surface"])
        require(not surface.get("_af_rt_fiber_surface_error"), "NATIVE_PUBLICATION_FAILED", str(surface.get("_af_rt_fiber_surface_error")))
        for kind, field in (("BASE", "base"), ("INFL", "inflated")):
            objects = [o for o in port.scene.objects if o.get("af_root_name") == port.root.name
                       and o.get("af_muscle_id") == identity["muscle"] and o.get("af_muscle_surface") == kind]
            require(len(objects) == 1, "NATIVE_PUBLICATION_FAILED", name+":"+kind)
            verify_mesh(objects[0], outputs[name][field], name)


def verify_mesh(obj, expected, name):
    require(obj.type == "MESH", "NATIVE_PUBLICATION_FAILED", name)
    actual = np.array([tuple(obj.matrix_world @ vertex.co) for vertex in obj.data.vertices])
    expected = np.asarray(expected)
    require(actual.shape == expected.shape, "NATIVE_PUBLICATION_FAILED", name+": vertex count")
    require(np.allclose(actual, expected, atol=2e-5, rtol=1e-5), "NATIVE_PUBLICATION_FAILED", name+": geometry mismatch")
