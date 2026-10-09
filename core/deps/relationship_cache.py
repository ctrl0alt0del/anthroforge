"""Bounded primitive relationship captures; exact payload equality guards raw writes."""
from collections import namedtuple
from itertools import count
from time import perf_counter

try:
    from .. import utils
    from ..vcp import fiber_node_attachment_codec as codec, shared_point_storage
    from ..vcp.fiber_modes import fiber_parent_ids
except ImportError:
    from core import utils
    from core.vcp import fiber_node_attachment_codec as codec, shared_point_storage
    from core.vcp.fiber_modes import fiber_parent_ids
from .drivers import dependency_driver_generation
from .runtime_trace import telemetry_count, telemetry_timing

OWNER_NAMESPACE = "dependency_owners"
GRAPH_NAMESPACE = "dependency_graphs"
OWNER_ENTRIES, GRAPH_ENTRIES = 8192, 16
OWNER_BYTES = GRAPH_BYTES = 64 * 1024 * 1024
_EPOCH = 0
_GENERATIONS = count(1)
Capture = namedtuple("Capture", "key records owners ambiguous")


class _CacheBucket:
    def as_pointer(self):
        return id(self)


_BUCKET = _CacheBucket()


def runtime_identity(value):
    if value is None: return 0
    original = getattr(value, "original", value)
    try: return int(getattr(original, "session_uid", 0) or original.as_pointer())
    except (AttributeError, ReferenceError, TypeError): return id(original)


def _scope(root, scene):
    return f"{_EPOCH}:root={runtime_identity(root)}:scene={runtime_identity(scene)}:"


def node_owner_ids(root, scene, fiber):
    raw = str(getattr(fiber, "node_attachments_json", "") or "")
    key = f"{OWNER_NAMESPACE}:{_scope(root, scene)}{runtime_identity(fiber)}:{codec.NODE_ATTACHMENT_VERSION}"
    telemetry_count("dependency_payload_reads"); telemetry_count("dependency_payload_bytes", len(raw.encode("utf8")))
    entry = utils.bounded_scene_cache_get(_BUCKET, key, OWNER_NAMESPACE)
    if entry is not None and entry[0] == raw:
        telemetry_count("dependency_owner_hits")
        return entry[1]
    telemetry_count("dependency_owner_misses"); telemetry_count("dependency_payload_decodes")
    owners = codec.node_attachment_target_ids_from_raw(raw)
    utils.bounded_scene_cache_set(_BUCKET, key, (raw, owners), OWNER_NAMESPACE, OWNER_ENTRIES, OWNER_BYTES)
    return owners


def _items(root, name):
    system = "af_scp_system" if name == "scps" else "af_vcp_system"
    return tuple(getattr(getattr(root, system, None), name, ()))


def _fields(item, *names):
    return tuple(str(getattr(item, name, "") or "") for name in names)


def _member(item):
    return (runtime_identity(item), str(item.id or ""))


def _references(item):
    return tuple(str(ref.fiber_id or "") for ref in getattr(item, "fiber_refs", ()))


def _binding_records(fiber):
    ends = _fields(fiber, "a_point_id", "a_parent_id", "b_point_id", "b_parent_id")
    touches = tuple(_fields(item, "point_id", "parent_id") for item in getattr(fiber, "mid_touches", ()))
    loops = tuple(_fields(item, "point_id", "parent_id", "attach_param") for item in getattr(fiber, "loop_anchors", ()))
    supports = tuple(str(row.target_id) for row in getattr(fiber, 'attachment_supports', ()))
    return ends, touches, loops, supports


def _fiber_records(root, scene):
    records, owners = [], []
    shared_point_storage.clear_indexes()  # Reconcile same-count shared point replacements before getters.
    for fiber in _items(root, "fibers"):
        nodes = node_owner_ids(root, scene, fiber)
        supports = tuple(row.target_id for row in getattr(fiber, 'attachment_supports', ()))
        parents = tuple(dict.fromkeys((*fiber_parent_ids(fiber), *nodes, *supports)))
        owners.append((runtime_identity(fiber), tuple(str(v) for v in parents if v)))
        records.append((_member(fiber), _fields(fiber, "topology_mode"), _binding_records(fiber), nodes))
    return tuple(records), tuple(owners)


def _surface_records(root):
    return tuple((_member(s), _fields(s, "construction_mode", "main_surface_id"), _references(s),
                  tuple(_fields(b, "surface_id") for b in getattr(s, "branches", ())))
                 for s in _items(root, "fiber_surfaces"))


def _muscle_records(root):
    return tuple((_member(m), _fields(m, "surface_source_mode", "fiber_surface_id"),
                  bool(getattr(m, "use_mirrored_rows", False)), _references(m)) for m in _items(root, "muscles"))


def _soft_target(item):
    if int(getattr(item, "schema_version", 1)) < 2:
        return "SCP", str(getattr(item, "host_scp_id", "") or ""), "SCP_GEOMETRY"
    return _fields(item, "attachment_target_type", "attachment_target_id", "attachment_target_surface")


def _other_records(root):
    scps = tuple((_member(s), _fields(s, "parent_id")) for s in _items(root, "scps"))
    blobs = tuple((_member(b), _fields(b, "attach_target_type", "attach_target_id")) for b in _items(root, "blobs"))
    tissues = tuple((_member(t), _fields(t, "base_source_type", "base_source_id"), _soft_target(t))
                    for t in _items(root, "soft_tissues"))
    return scps, blobs, tissues


def _resolve_instances(root, owners, scene):
    targets = {sid for _key, ids in owners for sid in ids if sid.startswith("AFI_")}
    if not targets or scene is None: return (), owners
    try: from ..scp_runtime.common import instance_geometry_index
    except ImportError: from core.scp_runtime.common import instance_geometry_index
    started = perf_counter(); objects, duplicates = instance_geometry_index(scene, root.name)
    mapping = {sid: _instance_record(sid, objects.get(sid), sid in duplicates) for sid in sorted(targets)}
    resolved = tuple((key, tuple(dict.fromkeys(mapping[sid][1] if sid in mapping else sid for sid in ids)))
                     for key, ids in owners)
    telemetry_timing("dependency_owner_resolution", (perf_counter() - started) * 1000)
    return tuple(mapping.items()), resolved


def _instance_record(sid, obj, ambiguous=False):
    if ambiguous: return (0, sid, "ambiguous")
    if obj is None: return (0, sid, "missing")
    return runtime_identity(obj), str(obj.get("af_source_scp_id") or obj.get("af_scp_id") or sid), "resolved"


def _ambiguous(root):
    for name in ("scps", "fibers", "fiber_surfaces", "muscles", "blobs", "soft_tissues", "authored_points"):
        ids = [str(item.id or "") for item in _items(root, name)]
        if len(set(ids)) != len(ids): return True
    return False


def capture_relationships(root, scene=None):
    from .surface_dependencies import stacking_signature
    started = perf_counter(); ownership_scene = utils.scene_for_id(root)
    fibers, owners = _fiber_records(root, scene)
    mappings, owners = _resolve_instances(root, owners, ownership_scene)
    records = (dependency_driver_generation(), fibers, _surface_records(root), _muscle_records(root),
               _other_records(root), runtime_identity(ownership_scene), mappings, stacking_signature(root))
    result = Capture(f"{GRAPH_NAMESPACE}:{_scope(root, scene)}", records, owners, _ambiguous(root))
    telemetry_timing("dependency_capture", (perf_counter() - started) * 1000)
    return result


def graph_entry(capture):
    return utils.bounded_scene_cache_get(_BUCKET, capture.key, GRAPH_NAMESPACE)


def reconcile_relationships(capture, entry=None):
    if entry is not None and not capture.ambiguous and entry[0] == capture.records:
        return entry[1]
    return next(_GENERATIONS)


def _graph_size(key, value):
    graph = value[2][0]; seen = set()
    size = utils._bounded_size((key, value), seen)
    size += utils._bounded_size(vars(graph), seen)
    for port in graph.ports.values():
        size += utils._bounded_size(vars(port), seen)
    for edge in graph.edges:
        size += utils._bounded_size(vars(edge), seen)
        # Equal-key port replacements can leave older ports alive in edges.
        size += utils._bounded_size(vars(edge.src), seen)
        size += utils._bounded_size(vars(edge.dst), seen)
    return size


def store_graph(capture, generation, data):
    if capture.ambiguous: return data
    value = capture.records, generation, data
    utils.bounded_scene_cache_set(_BUCKET, capture.key, value, GRAPH_NAMESPACE,
                                 GRAPH_ENTRIES, GRAPH_BYTES, _graph_size(capture.key, value))
    return data


def clear_relationship_cache(root=None):
    global _EPOCH
    if root is None: _EPOCH += 1
    marker = "" if root is None else f":root={runtime_identity(root)}:"
    for namespace in (OWNER_NAMESPACE, GRAPH_NAMESPACE):
        utils.clear_bounded_scene_cache(namespace, marker)
