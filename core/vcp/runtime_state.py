_FIBER_BOOL = "_af_rt_fiber_not_converged"
_FIBER_MS = "_af_rt_fiber_last_recompute_ms"
_FIBER_STATUS = "_af_rt_fiber_last_recompute_status"
_FIBER_DISP = "_af_rt_fiber_last_eps_disp"
_FIBER_PEN = "_af_rt_fiber_last_eps_pen"
_FIBER_ROUTE = "_af_rt_fiber_last_route_mode"
_FIBER_PLAN = "_af_rt_fiber_last_planner_ms"
_FIBER_REFINE = "_af_rt_fiber_last_refine_ms"
_FIBER_ACTIVE = "_af_rt_fiber_last_active_colliders"
_FIBER_INVALID = "_af_rt_fiber_last_invalid_reason"
_BLOB_OK = "_af_rt_blob_last_solve_converged"
_BLOB_DISP = "_af_rt_blob_last_solve_max_disp"
_BLOB_ITERS = "_af_rt_blob_last_solve_iterations"
_SURFACE_STATUS = "_af_rt_fiber_surface_status"
_SURFACE_MS = "_af_rt_fiber_surface_ms"
_SURFACE_ERROR = "_af_rt_fiber_surface_error"
_SOFT_STATUS = "_af_rt_soft_tissue_status"
_SOFT_MS = "_af_rt_soft_tissue_ms"
_SOFT_ITERS = "_af_rt_soft_tissue_iterations"
_SOFT_DISP = "_af_rt_soft_tissue_max_disp"
_SOFT_ERROR = "_af_rt_soft_tissue_error"


def fiber_not_converged(fiber):
    return bool(_read(fiber, _FIBER_BOOL, False))


def set_fiber_not_converged(fiber, value):
    _write(fiber, _FIBER_BOOL, bool(value))


def fiber_recompute_ms(fiber):
    return float(_read(fiber, _FIBER_MS, 0.0))


def set_fiber_recompute_ms(fiber, value):
    _write(fiber, _FIBER_MS, float(value))


def fiber_recompute_status(fiber):
    return str(_read(fiber, _FIBER_STATUS, "UNKNOWN") or "UNKNOWN")


def set_fiber_recompute_status(fiber, value):
    _write(fiber, _FIBER_STATUS, str(value or "UNKNOWN"))


def fiber_eps_disp(fiber):
    return float(_read(fiber, _FIBER_DISP, 0.0))


def set_fiber_eps_disp(fiber, value):
    _write(fiber, _FIBER_DISP, float(value))


def fiber_eps_pen(fiber):
    return float(_read(fiber, _FIBER_PEN, 0.0))


def set_fiber_eps_pen(fiber, value):
    _write(fiber, _FIBER_PEN, float(value))


def fiber_route_mode(fiber):
    return str(_read(fiber, _FIBER_ROUTE, "LOCAL_FALLBACK") or "LOCAL_FALLBACK")


def set_fiber_route_mode(fiber, value):
    _write(fiber, _FIBER_ROUTE, str(value or "LOCAL_FALLBACK"))


def fiber_planner_ms(fiber):
    return float(_read(fiber, _FIBER_PLAN, 0.0))


def set_fiber_planner_ms(fiber, value):
    _write(fiber, _FIBER_PLAN, float(value))


def fiber_refine_ms(fiber):
    return float(_read(fiber, _FIBER_REFINE, 0.0))


def set_fiber_refine_ms(fiber, value):
    _write(fiber, _FIBER_REFINE, float(value))


def fiber_active_colliders(fiber):
    return int(_read(fiber, _FIBER_ACTIVE, 0))


def set_fiber_active_colliders(fiber, value):
    _write(fiber, _FIBER_ACTIVE, int(value))


def fiber_invalid_reason(fiber):
    return str(_read(fiber, _FIBER_INVALID, "") or "")


def set_fiber_invalid_reason(fiber, value):
    _write(fiber, _FIBER_INVALID, str(value or ""))


def reset_fiber_runtime(fiber):
    set_fiber_not_converged(fiber, False)
    set_fiber_recompute_ms(fiber, 0.0)
    set_fiber_recompute_status(fiber, "UNKNOWN")
    set_fiber_eps_disp(fiber, 0.0)
    set_fiber_eps_pen(fiber, 0.0)
    set_fiber_route_mode(fiber, "LOCAL_FALLBACK")
    set_fiber_planner_ms(fiber, 0.0)
    set_fiber_refine_ms(fiber, 0.0)
    set_fiber_active_colliders(fiber, 0)
    set_fiber_invalid_reason(fiber, "")


def blob_solve_converged(blob):
    return bool(_read(blob, _BLOB_OK, False))


def set_blob_solve_converged(blob, value):
    _write(blob, _BLOB_OK, bool(value))


def blob_solve_max_disp(blob):
    return float(_read(blob, _BLOB_DISP, 0.0))


def set_blob_solve_max_disp(blob, value):
    _write(blob, _BLOB_DISP, float(value))


def blob_solve_iterations(blob):
    return int(_read(blob, _BLOB_ITERS, 0))


def set_blob_solve_iterations(blob, value):
    _write(blob, _BLOB_ITERS, int(value))


def reset_blob_runtime(blob):
    set_blob_solve_converged(blob, False)
    set_blob_solve_max_disp(blob, 0.0)
    set_blob_solve_iterations(blob, 0)


def muscle_inflation_ctrl_world(muscle):
    from .muscle_inflation_state import inflation_control_world
    return inflation_control_world(muscle)


def set_muscle_inflation_ctrl_world(muscle, value):
    from .muscle_inflation_state import set_inflation_control_world
    set_inflation_control_world(muscle, value)


def reset_muscle_runtime(muscle):
    from .muscle_inflation_state import migrate_inflation_control
    migrate_inflation_control(muscle)


def fiber_surface_status(surface):
    return str(_read(surface, _SURFACE_STATUS, "DIRTY") or "DIRTY")


def fiber_surface_diagnostic(surface):
    return float(_read(surface, _SURFACE_MS, 0.0)), str(_read(surface, _SURFACE_ERROR, "") or "")


def set_fiber_surface_runtime(surface, status, milliseconds=0.0, error=""):
    _write(surface, _SURFACE_STATUS, str(status or "DIRTY"))
    _write(surface, _SURFACE_MS, float(milliseconds))
    _write(surface, _SURFACE_ERROR, str(error or ""))


def reset_fiber_surface_runtime(surface):
    set_fiber_surface_runtime(surface, "DIRTY")


def soft_tissue_status(tissue):
    return str(_read(tissue, _SOFT_STATUS, "DIRTY") or "DIRTY")


def set_soft_tissue_status(tissue, value):
    _write(tissue, _SOFT_STATUS, str(value or "DIRTY"))


def soft_tissue_diagnostic(tissue):
    return (float(_read(tissue, _SOFT_MS, 0.0)), int(_read(tissue, _SOFT_ITERS, 0)),
            float(_read(tissue, _SOFT_DISP, 0.0)), str(_read(tissue, _SOFT_ERROR, "") or ""))


def set_soft_tissue_diagnostic(tissue, milliseconds=0.0, iterations=0, displacement=0.0, error=""):
    _write(tissue, _SOFT_MS, float(milliseconds))
    _write(tissue, _SOFT_ITERS, int(iterations))
    _write(tissue, _SOFT_DISP, float(displacement))
    _write(tissue, _SOFT_ERROR, str(error or ""))


def reset_soft_tissue_runtime(tissue):
    set_soft_tissue_status(tissue, "DIRTY")
    set_soft_tissue_diagnostic(tissue)


def reset_vcp_runtime_state(root):
    vcp = None if root is None else getattr(root, "af_vcp_system", None)
    if vcp is None:
        return
    for fiber in getattr(vcp, "fibers", ()):
        reset_fiber_runtime(fiber)
    for muscle in getattr(vcp, "muscles", ()):
        reset_muscle_runtime(muscle)
    for surface in getattr(vcp, "fiber_surfaces", ()):
        reset_fiber_surface_runtime(surface)
    for blob in getattr(vcp, "blobs", ()):
        reset_blob_runtime(blob)
    for tissue in getattr(vcp, "soft_tissues", ()):
        reset_soft_tissue_runtime(tissue)


def _vec3(value):
    try:
        data = tuple(value)
    except Exception:
        data = (0.0, 0.0, 0.0)
    return tuple(float(data[i] if i < len(data) else 0.0) for i in range(3))


def _read(prop, key, default):
    try:
        value = prop.get(key, default)
    except Exception:
        value = getattr(prop, key, default)
    return default if value is None else value


def _write(prop, key, value):
    stored = list(value) if isinstance(value, (list, tuple)) else value
    try:
        prop[key] = stored
    except Exception:
        setattr(prop, key, stored)
