import os
import sys

_ROOT = os.path.dirname(os.path.dirname(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from core.deps.controls import classify_control_object
except Exception:
    print("SKIP (requires Blender Python environment)")
    raise SystemExit(0)


class _FakeObj(dict):
    def __init__(self, name, **kwargs):
        super().__init__(**kwargs)
        self.name = name


def _assert(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _must_have_binding(o):
    c = classify_control_object(o)
    _assert(c is not None, f"classification failed for {o.name}")
    _assert("binding" in c and c["binding"] is not None, f"missing binding for {o.name}")


def main():
    root = "AF_ROOT"
    _must_have_binding(_FakeObj("scp_curve", af_root_name=root, af_curve_point_handle=True, af_scp_id="S1", af_curve_point_index=1))
    _must_have_binding(_FakeObj("scp_par", af_root_name=root, af_parallelepiped_vert_handle=True, af_scp_id="S1", af_parallelepiped_vert_index=2))
    _must_have_binding(_FakeObj("scp_clip", af_root_name=root, af_ellipsoid_clip_handle=True, af_scp_id="S1", af_ellipsoid_clip_index=1))
    _must_have_binding(_FakeObj("fiber_ep", af_root_name=root, af_fiber_endpoint_handle=True, af_fiber_id="F1", af_fiber_endpoint="A"))
    _must_have_binding(_FakeObj("fiber_touch", af_root_name=root, af_fiber_touch_handle=True, af_fiber_id="F1", af_fiber_touch_index=0))
    _must_have_binding(_FakeObj("muscle", af_root_name=root, af_muscle_inflation_ctrl=True, af_muscle_id="M1"))
    _must_have_binding(_FakeObj("blob", af_root_name=root, af_blob_control_gizmo=True, af_blob_id="B1"))
    print("OK")


if __name__ == "__main__":
    main()
