"""Verify visible native output before committing an authoring transaction."""
import numpy as np
from ...core.authoring.errors import require


def verify(port, ids, outputs, planes=None):
    for name, identity in ids.items():
        surface = next(s for s in port.root.af_vcp_system.fiber_surfaces if s.id == identity["surface"])
        require(not surface.get("_af_rt_fiber_surface_error"), "NATIVE_PUBLICATION_FAILED", str(surface.get("_af_rt_fiber_surface_error")))
        for kind, field in (("BASE", "base"), ("INFL", "inflated")):
            objects = [o for o in port.scene.objects if o.get("af_root_name") == port.root.name
                       and o.get("af_muscle_id") == identity["muscle"] and o.get("af_muscle_surface") == kind]
            verify_pair(objects, outputs[name][field], name+':'+kind, (planes or {}).get(name))


def verify_pair(objects, expected, name, plane):
    sources = [o for o in objects if not o.get('af_muscle_mirror_proxy')]
    mirrors = [o for o in objects if o.get('af_muscle_mirror_proxy')]
    require(len(sources) == 1 and len(mirrors) == int(plane is not None), 'NATIVE_PUBLICATION_FAILED', name)
    verify_mesh(sources[0], expected, name)
    if plane is not None:
        reflected = np.array(expected, dtype=float)
        axis = 'XYZ'.index(plane['axis'])
        reflected[:, axis] = 2*plane['origin'][axis]-reflected[:, axis]
        require(mirrors[0].get('af_source_muscle_id') == sources[0].get('af_muscle_id'), 'NATIVE_PUBLICATION_FAILED', name)
        require(mirrors[0].data == sources[0].data, 'NATIVE_PUBLICATION_FAILED', name+': mirror data is detached')
        verify_mesh(mirrors[0], reflected, name+':mirror')


def verify_mesh(obj, expected, name):
    require(obj.type == "MESH", "NATIVE_PUBLICATION_FAILED", name)
    actual = np.array([tuple(obj.matrix_world @ vertex.co) for vertex in obj.data.vertices])
    expected = np.asarray(expected)
    require(actual.shape == expected.shape, "NATIVE_PUBLICATION_FAILED", name+": vertex count")
    require(np.allclose(actual, expected, atol=2e-5, rtol=1e-5), "NATIVE_PUBLICATION_FAILED", name+": geometry mismatch")
