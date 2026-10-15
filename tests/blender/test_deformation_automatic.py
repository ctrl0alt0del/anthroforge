"""Real Blender change detection, edit coalescing, cancellation and stale rejection."""
import sys
import time
from pathlib import Path
import bpy
ROOT = Path(__file__).resolve().parents[2]; sys.path[:0] = [str(ROOT.parent),str(ROOT),str(Path(__file__).parent)]
import anthroforge
from anthroforge.adapters.deformation import runtime, request
from anthroforge.core.warnings import session
from test_deformation_worker import wait


def settings_only(root):
    runtime.discover(); key = session.id_token(root)
    root.af_draft_skin_settings.minimum_offset_percent *= .9
    runtime.discover()
    assert root.get("af_deformation_construction_stale") and key not in runtime.QUEUE.slots
    root.af_topology_settings.deformation_method = "FAST"; runtime.discover()
    assert key in runtime.QUEUE.slots
    root.af_topology_settings.deformation_method = "LE"; runtime.discover()
    assert len(runtime.QUEUE.slots) == 1


def edit_burst(root):
    obj = next(o for o in bpy.context.scene.objects if o.get("af_scp_geometry") and not o.get("af_mirror"))
    before = request.revision(root)
    for _ in range(3):
        obj.location.x += .001; bpy.context.view_layer.update(); runtime.discover()
    assert request.revision(root) != before
    key = session.id_token(root); assert len(runtime.QUEUE.slots) == 1
    runtime.enqueue(root,bpy.context.scene,True); runtime.tick(); assert key in runtime.jobs.ACTIVE
    obj.location.x -= .003; bpy.context.view_layer.update(); runtime.discover()
    assert Path(runtime.jobs.ACTIVE[key].spec.cancel_path).is_file()
    wait(root)


def run(path):
    anthroforge.register(); bpy.ops.wm.open_mainfile(filepath=str(path)); bpy.context.view_layer.update()
    root = bpy.data.objects["AF_ROOT"]; obj = request.topology(root,bpy.context.scene); pointer = obj.data.as_pointer()
    settings_only(root); edit_burst(root)
    assert obj.data.as_pointer() == pointer and not runtime.jobs.ACTIVE
    assert not any(o.get("af_draft_skin") for o in bpy.context.scene.objects)
    print("DEFORMATION_AUTOMATIC_PASS",flush=True)


if __name__ == "__main__":
    try: run(Path(sys.argv[sys.argv.index("--")+1]))
    finally: runtime.shutdown()
