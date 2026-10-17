"""Run real native and Blender integration tests inside the matching Blender host."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT.parent), str(ROOT), str(ROOT/'tests'), str(ROOT/'tests/unit'), str(ROOT/'tests/blender')]
from adapters.topology.vendor import ensure_worker_dependencies
ensure_worker_dependencies()


def main():
    from core.deformation.native import library
    from core.topology.flow_native import library as flow_library
    from core.vcp.v2.collision_native import load_native
    from core.vcp.height_smoothing_native import library as smoothing_library
    for load in (library, flow_library, load_native, smoothing_library):
        load()
    names = ['tests.unit.test_fiber_v3_production', 'tests.unit.test_fiber_tightening',
             'tests.unit.test_deformation_reference', 'tests.unit.test_deformation_contact',
             'tests.unit.test_branch_flow', 'test_fiber_tightening', 'test_authoring_storage_export']
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == '__main__':
    main()
