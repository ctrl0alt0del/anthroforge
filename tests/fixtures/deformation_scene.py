"""Reusable real-scene fixtures and debug visibility assertions."""

import bpy

import numpy as np

def load_fixture(source):
    bpy.ops.wm.open_mainfile(filepath=str(source)); root = bpy.data.objects["AF_ROOT"]
    print("RESTORE_TOPOLOGY",flush=True)
    obj = reference_topology(root,source); print("CAPTURE_BEGIN",flush=True)
    return root,obj

def reference_topology(root, source):
    from anthroforge.core.topology.protocol import read_result
    from anthroforge.adapters.topology.output import replace_topology
    result = read_result(source.parents[2]/"20261014_v19_issue_system/before_topology.npz")
    return replace_topology(bpy.context.scene,root,result)

def debug_visibility(root):
    fibers = [o for o in bpy.context.scene.objects if o.get("af_fiber_proxy")]
    hidden = [o.name for o in fibers if not o.visible_get() or o.display_type != "TEXTURED"]
    colors = {s.id:tuple(s.color) for s in root.af_scp_system.scps}
    scps = [o for o in bpy.context.scene.objects if o.get("af_scp_geometry")]
    mismatched = [o.name for o in scps if not np.allclose(o.color,colors[o.get("af_source_scp_id") or o.get("af_scp_id")])]
    views = [s for screen in bpy.data.screens for a in screen.areas for s in a.spaces if s.type == "VIEW_3D"]
    assert fibers and not hidden and not mismatched
    assert all(s.shading.type == "SOLID" and s.shading.color_type == "OBJECT" for s in views)
    return dict(fibers=len(fibers),hidden_fibers=hidden,scp_objects=len(scps),color_mismatches=mismatched)
