"""Keep unmanaged dependencies intact when a document removes native entities."""
import bpy
from ...core.authoring.errors import require


def validate_removal(root, old, wanted):
    fibers = old["fibers"]-wanted["fibers"]
    surfaces = old["fiber_surfaces"]-wanted["fiber_surfaces"]
    for group in ("muscles","fiber_surfaces"):
        for item in getattr(root.af_vcp_system,group):
            if item.id in old[group]:
                continue
            require(not any(ref.fiber_id in fibers for ref in item.fiber_refs), "UNMANAGED_DEPENDENCY", item.id)
            require(getattr(item,"fiber_surface_id","") not in surfaces, "UNMANAGED_DEPENDENCY", item.id)


def remove_proxies(root, old, wanted):
    keys = dict(fibers="af_fiber_id",fiber_surfaces="af_fiber_surface_id",muscles="af_muscle_id")
    for group,key in keys.items():
        removed = old[group]-wanted[group]
        for obj in tuple(bpy.data.objects):
            if obj.get("af_root_name") == root.name and obj.get(key) in removed:
                bpy.data.objects.remove(obj,do_unlink=True)
