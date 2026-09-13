"""Read-only Blender warning smoke probe: --python tools/warnings_probe.py -- FILE.blend."""
import importlib.util
import json
from pathlib import Path
import sys
from time import perf_counter


def load_addon():
    path = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location("anthroforge", path / "__init__.py", submodule_search_locations=[str(path)])
    module = importlib.util.module_from_spec(spec)
    sys.modules["anthroforge"] = module
    spec.loader.exec_module(module)
    module.register()
    assert Path(module.__file__).resolve().parent == path
    return path


def source_signature():
    import bpy
    from anthroforge.core.vcp.fiber_anchor_preflight import _raw_anchor_specs
    from anthroforge.core.warnings.model import fingerprint
    rows = [(scene.name, root.name, fiber.id, _raw_anchor_specs(fiber), fiber.collision_radius)
            for scene in bpy.data.scenes for root in scene.objects if root.get("anthroforge_root")
            for fiber in root.af_vcp_system.fibers]
    return fingerprint(rows), len(rows)


def run_checks(path):
    from anthroforge.core.warnings import session
    from anthroforge.core.warnings.query import WarningQuery
    sys.path.insert(0, str(path / "tests" / "blender"))
    from test_warning_repository import forbid_solves
    started, ticks = perf_counter(), 0
    with forbid_solves():
        while session.COORDINATOR.tick():
            ticks += 1
            if perf_counter() - started > 300:
                raise AssertionError("Diagnostic probe exceeded five minutes")
    result = WarningQuery().list(dict(limit=0))
    result.update(ticks=ticks, elapsed_seconds=perf_counter() - started)
    return result


def main():
    import bpy
    path = load_addon()
    filename = sys.argv[sys.argv.index("--") + 1]
    bpy.ops.wm.open_mainfile(filepath=str(Path(filename).resolve()))
    before, count = source_signature()
    result = run_checks(path)
    assert source_signature() == (before, count), "Diagnostics mutated authored pins/policy"
    result.update(authored_fibers=count, authored_signature_unchanged=True, addon_path=str(path))
    result.pop("source_generations", None)
    print("WARNING_PROBE " + json.dumps(result, sort_keys=True), flush=True)
    assert result["complete"], result
    incremental_probe(path)


def incremental_probe(path):
    import bpy
    from anthroforge.core.warnings import session
    from anthroforge.core.visualization.warning_runtime import notify_action
    session.COORDINATOR.metrics.clear()
    for scene in bpy.data.scenes:
        for root in scene.objects:
            if root.get("anthroforge_root") and root.af_vcp_system.fibers:
                for _index in range(10):
                    notify_action(root, scene, {"FIBER": {root.af_vcp_system.fibers[0].id}})
    result = run_checks(path)
    result.pop("source_generations", None)
    print("WARNING_INCREMENTAL " + json.dumps(result, sort_keys=True), flush=True)
    assert result["complete"], result


if __name__ == "__main__":
    main()
