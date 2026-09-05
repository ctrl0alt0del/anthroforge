"""Cached 3D overlay for invalid Fiber hard anchors."""

import bpy


_BATCHES = {}
_SHADER = None
_HANDLER = None
_CONTEXT_PROVIDER = None
_COLOR = (1.0, 0.08, 0.02, 1.0)
_POINT_SIZE = 14.0


def cache_fiber_anchor_overlay(scope, result):
    violations = tuple(getattr(result, "violations", ()) or ())
    if not violations:
        _BATCHES.pop(scope, None)
        return
    cached = _BATCHES.get(scope)
    if cached is not None and cached[0] == result.cache_key:
        return
    shader = _shader()
    if shader is None:
        return
    from gpu_extras.batch import batch_for_shader
    points = tuple(dict.fromkeys(row.point for row in violations))
    _BATCHES[scope] = result.cache_key, batch_for_shader(shader, "POINTS", {"pos": points})


def invalidate_fiber_anchor_overlay(scopes=None):
    if scopes is None:
        _BATCHES.clear()
        return
    for scope in tuple(scopes):
        _BATCHES.pop(scope, None)


def register_fiber_anchor_overlay(context_provider=None):
    global _HANDLER, _CONTEXT_PROVIDER
    _CONTEXT_PROVIDER = context_provider or _CONTEXT_PROVIDER
    if _HANDLER is None:
        if _shader() is None:
            return
        _HANDLER = bpy.types.SpaceView3D.draw_handler_add(
            _draw_invalid_anchors, (), "WINDOW", "POST_VIEW")


def unregister_fiber_anchor_overlay():
    global _HANDLER, _SHADER, _CONTEXT_PROVIDER
    invalidate_fiber_anchor_overlay()
    if _HANDLER is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_HANDLER, "WINDOW")
    _HANDLER, _SHADER, _CONTEXT_PROVIDER = None, None, None


def fiber_anchor_overlay_stats():
    return {"batches": len(_BATCHES), "registered": _HANDLER is not None}


def _shader():
    global _SHADER
    if _SHADER is None:
        import gpu
        try:
            _SHADER = gpu.shader.from_builtin("POINT_UNIFORM_COLOR")
        except SystemError:
            return None
    return _SHADER


def _draw_invalid_anchors():
    batch = _active_batch()
    if batch is None:
        return
    import gpu
    previous = gpu.state.blend_get(), gpu.state.depth_test_get()
    try:
        _draw_batch(gpu, batch)
    finally:
        gpu.state.blend_set(previous[0])
        gpu.state.depth_test_set(previous[1])


def _draw_batch(gpu, batch):
    shader = _shader()
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("LESS_EQUAL")
    shader.bind()
    shader.uniform_float("color", _COLOR)
    shader.uniform_float("size", _POINT_SIZE)
    batch.draw(shader)


def _active_batch():
    scope = _active_scope()
    cached = None if scope is None else _BATCHES.get(scope)
    return None if cached is None else cached[1]


def _active_scope():
    context = None if _CONTEXT_PROVIDER is None else _CONTEXT_PROVIDER()
    scene = getattr(context, "scene", None)
    root = _root_for_scene(scene)
    fiber = _active_fiber(root)
    if scene is None or root is None or fiber is None:
        return None
    if not _fiber_visible(context, scene, root, fiber):
        return None
    from ..vcp.fiber_anchor_preflight import fiber_anchor_scope
    return fiber_anchor_scope(scene, root, fiber)


def _fiber_visible(context, scene, root, fiber):
    from .category_visibility import fiber_proxy_visible
    viewport = getattr(context, "space_data", None)
    if getattr(viewport, "type", None) != "VIEW_3D":
        viewport = None
    return fiber_proxy_visible(scene, getattr(context, "view_layer", None), root, fiber.id, viewport)


def _root_for_scene(scene):
    if scene is None:
        return None
    from ..utils import get_af_root
    return get_af_root(scene)


def _active_fiber(root):
    system = getattr(root, "af_vcp_system", None)
    if system is None or str(getattr(system, "active_vcp_type", "")) != "FIBER":
        return None
    active = str(getattr(system, "active_vcp_id", "") or "")
    return next((row for row in system.fibers if str(row.id) == active), None)
