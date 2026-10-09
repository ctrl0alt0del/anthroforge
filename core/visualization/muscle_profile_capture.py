"""Read-only native chart capture: never solve fibers or create scene objects."""
from dataclasses import dataclass
from types import SimpleNamespace
import numpy as np
from ..vcp.fiber_modes import is_loop_fiber
from ..vcp.fiber_surface import evaluate_fiber_surface, FiberSurfaceSpec
from ..vcp.muscle_numeric import execute_muscle_batch, make_muscle_request
from ..vcp.muscle_section_profile import PROFILE_VERSION
from ..vcp.muscle_profile_cache import content_key, cached
from .fiber_sync_helpers import cached_fiber_points
from .muscle_sync_runtime import expanded_rows_with_provenance
from ..vcp.muscle_output_domain import DEFAULTS, revision as domain_revision
from ..vcp.free_path import is_free


@dataclass(frozen=True)
class ProfileTarget:
    muscle: object
    source: object
    payload: object = None
    chart: tuple = ()
    base_revision: str = ""
    current: bool = False
    reasons: tuple = ()
    assembly: object = None
    prepared_base: object = None

    @property
    def eligible(self):
        return self.current and not self.reasons


def find_target(root, muscle_id="", surface_id=""):
    vcp = root.af_vcp_system
    muscle = next((item for item in vcp.muscles if item.id == muscle_id), None) if muscle_id else None
    if muscle_id and muscle is None:
        raise ValueError("PROFILE_TARGET_NOT_FOUND: " + muscle_id)
    source_id = surface_id or (muscle.fiber_surface_id if muscle and muscle.surface_source_mode == "FIBER_SURFACE" else "")
    source = next((item for item in vcp.fiber_surfaces if item.id == source_id), None) if source_id else muscle
    if source is None and muscle is not None:
        source = SimpleNamespace(id=source_id, fiber_refs=())
    if source is None:
        raise ValueError("PROFILE_TARGET_NOT_FOUND: " + source_id)
    return muscle, source


def capture_target(root, scene, muscle_id="", surface_id="", index=None):
    muscle, source = find_target(root, muscle_id, surface_id)
    reasons = _domain_reasons(root, source)
    try:
        if getattr(source, 'construction_mode', '') == 'BRANCHED_LOFT':
            return _branched_target(root, scene, muscle, source, reasons, index)
        fibers, rows = current_rows(root, scene, source, index)
        rows, chart = expanded_rows_with_provenance(root, source, rows, fibers)
        payload = _payload(source, fibers, rows)
        revision, prepared = _prepared_revision(payload, chart, source)
        return ProfileTarget(muscle, source, payload, chart, domain_revision(revision, muscle), True, reasons, prepared_base=prepared)
    except (ValueError, TypeError) as error:
        return ProfileTarget(muscle, source, reasons=(str(error), *reasons))


def _branched_target(root, scene, muscle, source, reasons, index=None):
    from .branched_surface_capture import capture_assembly, source_surface
    from ..vcp.branched_surface import assemble
    sources = (source.main_surface_id, *(c.surface_id for c in source.branches))
    for key in sources:
        current_rows(root, scene, source_surface(root, key), index)
    assembly = capture_assembly(root, scene, source)
    vertices, faces = assemble(assembly)
    keys = tuple((c.id, c.boundary_fiber_id, tuple(r.point_id for r in c.roots)) for c in source.branches)
    revision = domain_revision(content_key(vertices, PROFILE_VERSION, source.id, sources, keys, faces.tolist()), muscle)
    return ProfileTarget(muscle, source, base_revision=revision, current=True, reasons=reasons, assembly=assembly)


def _source_fibers(root, source):
    by_id = {item.id: item for item in root.af_vcp_system.fibers}
    return tuple(by_id.get(ref.fiber_id) for ref in source.fiber_refs)


def _domain_reasons(root, source):
    try:
        validate_domain(source, _source_fibers(root, source))
    except (ValueError, TypeError) as error:
        return (str(error),)
    return ()


def validate_domain(source, fibers):
    mode = str(getattr(source, "construction_mode", "LOFT"))
    closed = bool(getattr(source, "close_across_fibers", getattr(source, "closed_v", False)))
    present = tuple(item for item in fibers if item is not None)
    if mode != "LOFT" or closed or any(is_loop_fiber(item) for item in present):
        raise ValueError("PROFILE_DOMAIN_UNSUPPORTED: Section Profile requires an ordinary open loft.")
    if present and not any(is_free(f) for f in present) and len({int(item.node_count) for item in present}) != 1:
        raise ValueError("PROFILE_GRID_INVALID: source fibers must share a node count.")


def current_rows(root, scene, source, index=None):
    from .vcp_object_index import build_vcp_object_index
    index = build_vcp_object_index(scene, root.name) if index is None else index
    fibers = _source_fibers(root, source)
    if not fibers or any(item is None for item in fibers):
        raise ValueError("PROFILE_BASE_NOT_CURRENT: Update source fibers first.")
    _check_source_proxies(root, scene, source, fibers, index)
    rows = [cached_fiber_points(scene, root.name, item.id, index=index) for item in fibers]
    if any(row is None or len(row) < 2 for row in rows):
        raise ValueError("PROFILE_BASE_NOT_CURRENT: Update source fibers first.")
    from .geometry_instance import row
    return fibers, [row(root, scene, fiber, points) for fiber, points in zip(fibers, rows)]


def _check_source_proxies(root, scene, source, fibers, index=None):
    from .vcp_object_index import build_vcp_object_index
    index = build_vcp_object_index(scene, root.name) if index is None else index
    for fiber in fibers:
        proxy = index['fiber'].get(str(fiber.id))
        if proxy is None or proxy.get("af_fiber_output_state") != "CURRENT":
            raise ValueError("PROFILE_BASE_NOT_CURRENT: Update source fibers first.")
    stale = any(obj.get('af_fiber_surface_id') == source.id and obj.get('af_fiber_surface_output_state') == 'STALE'
                for obj in index['fiber_surface'].values())
    if stale:
        raise ValueError("PROFILE_BASE_NOT_CURRENT: Update source fibers first.")


def _payload(source, fibers, rows):
    if any(is_free(f) for f in fibers): return _free_payload(source, fibers, rows)
    target, densify = int(fibers[0].node_count), not hasattr(source, "construction_mode")
    closed = bool(is_loop_fiber(fibers[0]))
    if not densify:
        from .fiber_surface_sync import _surface_spec, _validate_sources
        _validate_sources(source, fibers)
        rows = evaluate_fiber_surface(rows, _surface_spec(source, fibers)).rows
    return np.asarray(rows, dtype=float), target, densify, closed, source


def _free_payload(source, fibers, rows):
    from ..vcp.free_surface_stations import prepare_record
    closed = bool(is_loop_fiber(fibers[0]))
    grid = prepare_record(source, fibers, rows, closed)
    return np.asarray(grid, dtype=float), len(grid[0]), False, closed, source, True


def default_muscle():
    return SimpleNamespace(id="preview", inflation_enabled=False, inflation_mode="CTRL_POINT", inflation_max_value=.05,
        inflation_falloff_type="GAUSSIAN", inflation_falloff_radius=.2, inflation_direction_depth=.05,
        inflation_boundary_strength=.7, inflation_boundary_band=2., inflation_boundary_power=1.5,
        inflation_length_taper_band=.2, closed_v=False, flip_normals=False,
        inflation_ctrl_world=(0., 0., 0.), inflation_ctrl_initialized=False, id_data=None, **DEFAULTS,
        envelope_version=0, envelope_sides="ONE_SIDE", envelope_enabled=True, envelope_reverse=False,
        get=lambda key, default=None: default)


def _revision(payload, chart, source):
    return _prepared_revision(payload, chart, source)[0]


def _prepared_revision(payload, chart, source):
    from .muscle_numeric_runtime import _make_request
    from ..vcp.muscle_profile_numeric import prepare_profile, prepared_key, PreparedBase
    from ..vcp.muscle_numeric import resolve_muscle_backend
    request = _make_request(default_muscle(), payload)
    backend = resolve_muscle_backend().value
    result = prepare_profile(request, backend, execute_muscle_batch)
    if result.error: raise ValueError(result.error)
    from ..vcp.muscle_section_profile import checked_grid
    checked_grid(result.base_vertices.reshape(result.row_count, result.column_count, 3))
    identities = tuple((row["fiber_id"], row["mirrored"]) for row in chart)
    key = prepared_key(request, backend)
    revision = cached(('profile-revision', key, source.id, identities), lambda: _revision_digest(result, payload, source.id, identities))
    return revision, PreparedBase(key, result)


def _revision_digest(result, payload, source_id, identities):
    return content_key(result.base_vertices, PROFILE_VERSION, source_id, identities,
                       payload[0].tolist(), np.sort(result.faces, axis=1).tolist())
