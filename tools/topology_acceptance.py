import argparse
from pathlib import Path
import sys

import bpy

ADDON_ROOT = Path(__file__).resolve().parents[1]
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--target", type=int, required=True)
    parser.add_argument("--symmetry", choices=("NONE", "X", "Y", "Z"), required=True)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _register():
    import anthroforge
    if not hasattr(bpy.types.Object, "af_topology_settings"):
        anthroforge.register()


def _root():
    return next((obj for obj in bpy.context.scene.objects if obj.get("af_root")),
                bpy.context.scene.objects.get("AF_ROOT"))


def _update(stage, progress, message):
    print(f"[{progress:0.2f}] {stage}: {message}", flush=True)


def _run(root, arguments):
    from adapters.topology.capture import capture_topology
    from adapters.topology.output import replace_topology
    from adapters.topology.vendor import ensure_worker_dependencies
    vendor = ensure_worker_dependencies()
    from adapters.topology.solver import solve_capture
    depsgraph = bpy.context.evaluated_depsgraph_get()
    capture = capture_topology(root, bpy.context.scene, depsgraph)
    result = solve_capture(capture, vendor, _update)
    replace_topology(bpy.context.scene, root, result)
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(arguments.output).resolve()))


def main():
    arguments = _arguments(); _register(); root = _root()
    if root is None:
        raise RuntimeError("Acceptance scene has no AF_ROOT.")
    root.af_topology_settings.target_quad_count = arguments.target
    root.af_topology_settings.symmetry_mode = arguments.symmetry
    _run(root, arguments)


if __name__ == "__main__":
    main()
