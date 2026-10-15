"""Exercise ordinary topology construction and the explicit full rebuild transaction."""
import sys
import time
from pathlib import Path
import bpy
ROOT = Path(__file__).resolve().parents[2]; sys.path[:0] = [str(ROOT.parent),str(ROOT),str(ROOT/"tests")]
import anthroforge
from anthroforge.app.use_cases import topology, warm_update
from anthroforge.adapters.deformation import storage, request, runtime
from anthroforge.adapters.authoring.scene import StaticScene
from fixtures.deformation_scene import debug_visibility
BASE = Path("E:/development/WIP_models/rib_rig_experiment")
OUT = BASE/"20261015_v32_production_deformation"


def wait(poll, complete):
    deadline = time.monotonic()+1800
    while time.monotonic()<deadline:
        status = poll(bpy.context)
        if status.state in {"SUCCEEDED","PARTIAL","FAILED","CANCELLED"}:
            result = complete(bpy.context,status)
            assert result.ok,result.message
            print("BUILD_STAGE",result.message,flush=True); return
        time.sleep(.25)
    raise TimeoutError("Construction worker exceeded test deadline.")


def verify(name):
    root = bpy.data.objects["AF_ROOT"]; obj = request.topology(root,bpy.context.scene)
    signature = storage.load(root,obj).signature
    assert not any(o.get("af_draft_skin") for o in bpy.context.scene.objects)
    path = OUT/f"{name}_debug.blend"; StaticScene(root,bpy.context.scene).save_debug_copy(path)
    bpy.ops.wm.open_mainfile(filepath=str(path)); root = bpy.data.objects["AF_ROOT"]
    assert storage.load(root,request.topology(root,bpy.context.scene)).signature == signature
    print("BUILD_VERIFIED",name,debug_visibility(root),flush=True)


def run():
    anthroforge.register(); bpy.ops.wm.open_mainfile(filepath=str(BASE/"20261014_v21_large_diff/change_0/source_debug.blend"))
    restore_draft()
    bpy.data.objects["AF_ROOT"].af_topology_settings.symmetry_mode = "Y"
    result = topology.start_generation(bpy.context); assert result.ok,result.message
    wait(topology.poll_generation,topology.complete_generation); verify("built")
    result = warm_update.start_update(bpy.context,"FORCE_FULL"); assert result.ok,result.message
    wait(warm_update.poll_update,warm_update.complete_update); verify("rebuilt")
    print("DEFORMATION_BUILD_PASS",flush=True)


def restore_draft():
    from anthroforge.core.draft_skin.protocol import read_result
    from anthroforge.adapters.draft_skin.output import replace_draft_skin
    result = read_result(BASE/"20261014_v19_issue_system/before_skin.npz")
    replace_draft_skin(bpy.context.scene,bpy.data.objects["AF_ROOT"],result,{})


if __name__ == "__main__":
    try: run()
    finally:
        runtime.shutdown()
        from anthroforge.adapters.warm_update.jobs import shutdown_jobs
        shutdown_jobs()
