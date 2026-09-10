"""Configure mirror metadata consumed by the ordinary VCP mirror runtime."""
from .native import find


def configure(root, ids, plane):
    for identity in ids['fibers'].values():
        fiber = find(root.af_vcp_system.fibers, identity)
        fiber['af_authoring_symmetry'] = 'native_mirror' if plane else 'explicit'
        for key in ('axis', 'origin'):
            field = 'af_authoring_mirror_'+key
            if plane:
                fiber[field] = plane[key]
            elif field in fiber:
                del fiber[field]
