"""Main-thread Blender capture; workers receive only owned immutable arrays."""
from dataclasses import fields, is_dataclass, replace
from hashlib import sha256
from time import perf_counter
import numpy as np
from .field import export
from .model import snapshot

_PUBLISHED = {}
_FIELDS = {}
_LAST_VALID = {}


def identity(value):
    return str(getattr(value, 'session_uid', 0) or value.as_pointer())


def fingerprint(value):
    if isinstance(value, np.ndarray):
        return (str(value.dtype), value.shape, sha256(value.tobytes()).hexdigest())
    if is_dataclass(value): return tuple((f.name, fingerprint(getattr(value, f.name))) for f in fields(value))
    if isinstance(value, dict): return tuple((k, fingerprint(v)) for k, v in sorted(value.items()))
    if isinstance(value, (tuple, list)): return tuple(fingerprint(v) for v in value)
    return value


def remember(root, work, result, scene=None):
    from ..muscle_stacking.publication import forget
    forget(identity(root), str(work.muscle.id))
    _PUBLISHED[(identity(root), str(work.muscle.id))] = (fingerprint(work.request), result)
    if scene is not None:
        from .runtime import refresh
        refresh(scene, root)


def clear():
    from ..muscle_stacking.publication import forget
    forget()
    _PUBLISHED.clear(); _FIELDS.clear(); _LAST_VALID.clear()


def remove(root_id):
    from ..muscle_stacking.publication import forget
    forget(root_id)
    for cache in (_PUBLISHED, _FIELDS, _LAST_VALID):
        for token in tuple(cache):
            if token[0] == root_id: cache.pop(token)


def request_for(root, scene, muscle):
    from ..visualization.muscle_profile_capture import capture_target
    from ..visualization.muscle_numeric_runtime import _make_request, _make_branched_request, _initialize_control
    target = capture_target(root, scene, muscle.id)
    if not target.current: raise ValueError('; '.join(target.reasons))
    if target.assembly is not None: return _make_branched_request(muscle, target.source, target.assembly)
    request = _make_request(muscle, target.payload, _initialize_control(muscle))
    return replace(request, prepared_base=target.prepared_base)


def evaluate(root, request):
    from ..vcp.muscle_numeric import execute_muscle_batch
    key = identity(root), str(request.muscle_id); content = fingerprint(request)
    prior = _PUBLISHED.get(key)
    if prior is not None and prior[0] == content: return prior[1]
    result = execute_muscle_batch((request,), 'NATIVE').results[0]
    if result.error: raise ValueError(result.error)
    _PUBLISHED[key] = content, result
    return result


def geometry(obj):
    points = np.empty((len(obj.data.vertices), 3)); obj.data.vertices.foreach_get('co', points.ravel())
    matrix = np.asarray(obj.matrix_world, dtype=float)
    return points @ matrix[:3, :3].T + matrix[:3, 3]


def validate_surface(obj, expected):
    if obj is None or obj.get('af_muscle_output_state', 'CURRENT') != 'CURRENT': raise ValueError('PAIR_SURFACE_NOT_CURRENT')
    actual = geometry(obj)
    if actual.shape != expected.shape or not np.allclose(actual, expected, atol=5e-6, rtol=2e-6):
        raise ValueError('PAIR_SURFACE_CANONICAL_MISMATCH')


def mirror_domains(domains, source, mirror):
    from ..muscle_stacking.material import transformed
    if mirror is None: return ()
    matrix = np.asarray(mirror.matrix_world @ source.matrix_world.inverted(), dtype=float)
    values = []
    for domain in domains:
        base, own = (v @ matrix[:3, :3].T + matrix[:3, 3] for v in (domain.base, domain.own))
        direction = domain.direction @ matrix[:3, :3].T
        direction /= np.maximum(np.linalg.norm(direction, axis=1)[:, None], 1e-30)
        faces = domain.faces[:, ::-1] if np.linalg.det(matrix[:3, :3]) < 0 else domain.faces
        value = snapshot(replace(domain.key, instance='mirror'), domain.group, domain.revision,
            base, own, direction, faces, domain.parts, domain.sources, domain.displacement)
        values.append(replace(value, material=transformed(domain.material, matrix), output_indices=domain.output_indices))
    return tuple(values)


def capture_muscle(root, scene, muscle, settings, objects):
    from ..muscle_stacking.publication import expected
    from ..visualization.muscle_sync_helpers import resolve_muscle_surface
    request = request_for(root, scene, muscle); result = evaluate(root, request)
    base = resolve_muscle_surface(root, muscle.id, 'BASE', scene); outer = resolve_muscle_surface(root, muscle.id, 'INFL', scene)
    validate_surface(base, result.base_vertices); validate_surface(outer, expected(root, muscle.id, outer, result.inflated_vertices))
    group = str(muscle.get('af_pair_group_id', '') or muscle.id)
    revision = sha256(repr(fingerprint(request)).encode()).hexdigest()
    domains = cached_fields(root, muscle.id, group, revision, request, result, settings.displacement)
    mirrors = [o for o in objects if o.get('af_muscle_mirror_proxy') and o.get('af_source_muscle_id') == muscle.id and o.get('af_muscle_surface') == 'INFL']
    if len(mirrors) > 1: raise ValueError('PAIR_DUPLICATE_MIRROR')
    if mirrors: validate_mirror(outer, mirrors[0], result.inflated_vertices, root, muscle.id)
    return domains + mirror_domains(domains, outer, mirrors[0] if mirrors else None)


def validate_mirror(source, mirror, vertices, root=None, muscle=None):
    from ..muscle_stacking.publication import expected
    matrix = np.asarray(mirror.matrix_world @ source.matrix_world.inverted(), dtype=float)
    values = vertices @ matrix[:3, :3].T + matrix[:3, 3]
    validate_surface(mirror, expected(root, muscle, mirror, values, 'mirror') if root else values)


def cached_fields(root, muscle_id, group, revision, request, result, displacement):
    from ..muscle_relationships.identity import namespace
    key = identity(root), str(muscle_id); signature = namespace(root), group, revision, displacement
    prior = _FIELDS.get(key)
    if prior is None or prior[0] != signature:
        _FIELDS[key] = signature, export(namespace(root) or key[0], muscle_id, group, revision, request, result, displacement)
    return _FIELDS[key][1]


class DomainCaptureAdapter:
    def capture(self, scope, settings):
        from ..muscle_stacking.obstacles import capture
        scene, root = scope; start = perf_counter(); domains, issues = [], []
        for layer in scene.view_layers: layer.update()
        objects = tuple(o for o in scene.objects if o.get('af_root_name') == root.name)
        live = {(identity(root), str(m.id)) for m in root.af_vcp_system.muscles}
        prune(identity(root), live)
        for muscle in root.af_vcp_system.muscles:
            try: domains.extend(remember_domains(root, scene, muscle, settings, objects))
            except (ValueError, RuntimeError, TypeError, AttributeError) as error:
                domains.extend(replace(d, valid=False) for d in _LAST_VALID.get((identity(root), muscle.id), ()))
                issues.append(dict(muscle=muscle.id, message=str(error)))
        domains = conservative_invalid(root, domains, issues)
        bones = capture(scene, root)
        return tuple(replace(d, obstacles=bones) for d in domains), tuple(issues), dict(capture_ms=(perf_counter()-start)*1000)


def prune(root_id, live):
    for cache in (_PUBLISHED, _FIELDS, _LAST_VALID):
        for key in tuple(cache):
            if key[0] == root_id and key not in live: cache.pop(key)


def remember_domains(root, scene, muscle, settings, objects):
    result = capture_muscle(root, scene, muscle, settings, objects)
    _LAST_VALID[(identity(root), muscle.id)] = result
    return result


def conservative_invalid(root, domains, issues):
    unknown = any(not _LAST_VALID.get((identity(root), item['muscle'])) for item in issues)
    return [replace(d, valid=False) for d in domains] if unknown else domains
