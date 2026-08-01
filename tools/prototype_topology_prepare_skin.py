import argparse
import json
import sys
from pathlib import Path

import bpy


ADDON_ROOT = Path(__file__).resolve().parents[1]
for entry in (ADDON_ROOT.parent, ADDON_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def ensure_runtime():
    import anthroforge
    if not hasattr(bpy.types.Object, "af_scp_system"):
        anthroforge.register()
    from adapters.draft_skin.vendor import ensure_worker_dependencies
    ensure_worker_dependencies()


def scene_root():
    root = next((obj for obj in bpy.context.scene.objects if obj.get("anthroforge_root")), None)
    if root is None:
        raise RuntimeError("The scene has no AnthroForge root.")
    return root


def progress(stage, value, message=""):
    print(f"AF_SKIN_PROGRESS {value:.3f} {stage}: {message}", flush=True)


def generate_skin():
    from adapters.draft_skin.capture import capture_skin
    from app.runtime_api import sync_context
    from core.draft_skin.solver import solve_capture
    root = scene_root()
    sync_context(bpy.context, bake=True, source="topology_test", event_type="BAKE")
    bpy.context.view_layer.update()
    capture = capture_skin(root, bpy.context.scene, bpy.context.evaluated_depsgraph_get())
    return root, capture, solve_capture(capture, progress, lambda: False)


def install_skin(root, result):
    from adapters.draft_skin.output import replace_draft_skin
    source_map = result.statistics.get("source_map", [])
    return replace_draft_skin(bpy.context.scene, root, result, source_map)


def result_payload(capture, result):
    return {
        "sources": len(capture.sources),
        "source_types": sorted({item.entity_type for item in capture.sources}),
        "vertices": len(result.vertices),
        "triangles": len(result.triangles),
        "statistics": result.statistics,
    }


def main():
    args = parse_args()
    ensure_runtime()
    root, capture, result = generate_skin()
    install_skin(root, result)
    bpy.ops.wm.save_as_mainfile(filepath=args.output, copy=True, compress=False)
    print("AF_SKIN_RESULT " + json.dumps(result_payload(capture, result)), flush=True)


if __name__ == "__main__":
    main()
