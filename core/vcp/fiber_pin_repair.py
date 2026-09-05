"""Resumable on-demand repair for invalid authored Fiber pins."""

from math import cos, sin, tau
from time import perf_counter

import numpy as np
from mathutils import Vector

from ..attachment_codec import encode_fiber_surface_param
from ..scp_runtime.common import find_geometry_mesh_scp_obj
from ..scp_runtime.surface import build_mesh_surface_data
from .attachment_backend import attachment_runtime, capture_attachment_from_object, resolve_surface_frame
from .fiber_anchor_preflight import (_capture_colliders, _clearance_slack, _collider_probe_rows,
                                     _collision_world, _raw_anchor_specs, _source_key,
                                     preflight_fiber_hard_anchors,
                                     preflight_fiber_hard_anchors_in_world)
from .fiber_collision import CollisionOracle
from .fiber_pin_repair_policy import (FiberPinCandidate, FiberPinFailure, FiberPinRef,
                                      FiberPinRepair, FiberPinRepairPlan, FiberPinRepairReport,
                                      auto_repair_search_distance, serialization_guard,
                                      use_owner_transfer)
from .prop_update_guard import suppress_vcp_prop_updates


class _CandidateSampler:
    def __init__(self, surface, subdivision, offset, owner, threshold, world):
        self.surface = surface; self.subdivision = max(1, int(subdivision))
        self.offset = float(offset); self.owner = str(owner); self.threshold = float(threshold)
        self.world = world; self.triangle = 0; self.weights = tuple(_weights(self.subdivision))
        self.weight = 0; self.valid = []; self.pending = []; self.done = False

    def step(self, limit=128):
        if self.surface is None: self.done = True; return True
        self.pending.extend(self._rows(limit))
        complete = self.triangle >= len(self.surface["triangles"])
        if len(self.pending) >= 128 or complete: self._flush()
        self.done = bool(complete and not self.pending)
        return self.done

    def _flush(self):
        self.valid.extend(_valid_rows(self.world, self.pending, self.owner, self.threshold))
        self.pending.clear()

    def _rows(self, limit):
        rows = []
        while len(rows) < int(limit) and self.triangle < len(self.surface["triangles"]):
            rows.append(self._row()); self._advance()
        return rows

    def _row(self):
        tri = tuple(int(value) for value in self.surface["triangles"][self.triangle])
        return _triangle_row(self.surface, tri, self.weights[self.weight], self.offset)

    def _advance(self):
        self.weight += 1
        if self.weight >= len(self.weights): self.weight = 0; self.triangle += 1


class _ProjectedRefiner:
    def __init__(self, world, obj, runtime, pin, rows, threshold, limits=(8, 32, 18)):
        source = Vector(pin.point)
        self.world = world; self.obj = obj; self.runtime = runtime; self.pin = pin
        self.threshold = float(threshold); self.source = source
        self.seed_limit, self.path_steps, self.bisect_steps = tuple(map(int, limits))
        self.seeds = sorted(rows, key=lambda row: (Vector(row["point"]) - source).length_squared)[:self.seed_limit]
        self.seed = 0; self.bisect = 0; self.intervals = []; self.results = []
        self.done = not self.seeds

    def step(self):
        if self.done: return True
        if self.seed < len(self.seeds): self._step_scan()
        elif self.bisect: self._step_bisect()
        else: self._finish()
        return self.done

    def result(self):
        if not self.results: return None
        return min(self.results, key=lambda row: (Vector(row["point"]) - self.source).length_squared)

    def _step_scan(self):
        rows = tuple(self._candidate(self.seed, index / self.path_steps)
                     for index in range(1, self.path_steps + 1))
        match = _first_valid(rows, self.world, self.pin.owner, self.threshold)
        if match is None: self.results.append(self.seeds[self.seed])
        else: self._add_interval(match)
        self.seed += 1
        if self.seed == len(self.seeds): self.bisect = self.bisect_steps if self.intervals else 0

    def _step_bisect(self):
        rows = tuple(self._candidate(row[0], 0.5 * (row[1] + row[2])) for row in self.intervals)
        flags = _valid_flags(rows, self.world, self.pin.owner, self.threshold)
        for interval, candidate, valid in zip(self.intervals, rows, flags):
            _update_interval(interval, candidate, valid)
        self.bisect -= 1
        if not self.bisect: self._finish()

    def _candidate(self, seed_index, alpha):
        seed = self.seeds[seed_index]; target = self.source.lerp(Vector(seed["surface"]), alpha)
        return _candidate_from_target(self.obj, self.runtime, target, self.pin.offset)

    def _add_interval(self, match):
        index, row = match
        self.intervals.append([self.seed, index / self.path_steps,
                               (index + 1) / self.path_steps, row])

    def _finish(self):
        self.results.extend(row[3] for row in self.intervals)
        self.done = True


class FiberPinRepairSession:
    def __init__(self, root, scene, depsgraph, solver):
        self.root = root; self.scene = scene; self.depsgraph = depsgraph; self.solver = solver
        self.fibers = tuple(root.af_vcp_system.fibers); self.started = perf_counter()
        self.signature = fiber_pin_repair_signature(root, scene); self.phase = "CAPTURE"
        self.fiber_index = 0; self.pins = []; self.pin_index = 0; self.repairs = []; self.failures = []
        self.surfaces = {}; self.candidates = {}; self.sampler = None; self.refiner = None
        self.task = None; self.current = None; self.alternate = None; self.subdivision = 4
        self.runtime = None; self.world = None; self.colliders = ()
        self.done = False; self.cancelled = False

    def step(self, budget_ms=12.0):
        deadline = perf_counter() + max(0.0, float(budget_ms)) / 1000.0
        while not self.done and perf_counter() < deadline:
            phase, sampler, refiner = self.phase, self.sampler, self.refiner; self._advance()
            if _yield_after_advance(phase, sampler, refiner, self): break
        return self.progress()

    def progress(self):
        total = max(1, len(self.fibers) + len(self.pins))
        value = self.fiber_index + self.pin_index
        return {"phase": self.phase, "done": self.done, "current": min(value, total), "total": total}

    def cancel(self):
        self.cancelled = True; self.done = True; self.phase = "CANCELLED"

    def plan(self):
        elapsed = 1000.0 * (perf_counter() - self.started)
        ids = tuple(str(row.id) for row in self.fibers)
        return FiberPinRepairPlan(self.signature, ids, tuple(self.repairs), tuple(self.failures), elapsed)

    def stale(self):
        return self.signature != fiber_pin_repair_signature(self.root, self.scene)

    def _advance(self):
        if self.cancelled: self.cancel(); return
        if self.phase == "CAPTURE": self._capture(); return
        if self.phase == "PREFLIGHT": self._advance_preflight(); return
        if self.phase == "REPAIR": self._advance_repair(); return
        self.done = True

    def _capture(self):
        self.runtime = attachment_runtime(self.scene, self.depsgraph)
        self.world, self.colliders = _repair_world(self)
        self.phase = "PREFLIGHT"

    def _advance_preflight(self):
        if self.fiber_index >= len(self.fibers): self._finish_preflight(); return
        fiber = self.fibers[self.fiber_index]
        result = preflight_fiber_hard_anchors_in_world(
            self.root, self.scene, fiber, self.solver, self.depsgraph,
            self.colliders, self.world, self.signature, "FINAL")
        self.pins.extend(_invalid_pin_refs(fiber, result)); self.fiber_index += 1

    def _finish_preflight(self):
        self.pins = list(_dedupe_pins(self.pins)); self.phase = "REPAIR" if self.pins else "DONE"
        if not self.pins: self.done = True

    def _advance_repair(self):
        if self.pin_index >= len(self.pins): self.phase = "DONE"; self.done = True; return
        if self.task is None: self._start_task(self.pins[self.pin_index])
        self._step_task()

    def _start_task(self, pin):
        self.task = pin; self.current = None; self.alternate = None; self.subdivision = 4
        self.sampler = None; self.refiner = None

    def _step_task(self):
        if self.current is None: self._step_owner(self.task.owner, False); return
        if _needs_alternate(self.task, self.current) and self.alternate is None:
            self._step_owner(self.task.blocker, True); return
        self._finish_task()

    def _step_owner(self, owner, alternate):
        key = _candidate_key(self.task, owner, self.subdivision, self.colliders)
        rows = self.candidates.get(key)
        if rows is None: self._step_sampler(key, owner); return
        if self.refiner is None: self.refiner = self._new_refiner(owner, rows)
        if not self.refiner.step(): return
        self._store_refined(alternate, self.refiner.result())

    def _step_sampler(self, key, owner):
        if self.sampler is None: self.sampler = self._new_sampler(owner)
        if not self.sampler.step(): return
        self.candidates[key] = tuple(self.sampler.valid); self.sampler = None

    def _new_sampler(self, owner):
        surface = self._surface(owner); threshold = _repair_threshold(self.colliders, self.task.radius)
        return _CandidateSampler(surface, self.subdivision, self.task.offset, owner, threshold, self.world)

    def _new_refiner(self, owner, rows):
        pin = _pin_with_owner(self.task, owner); threshold = _repair_threshold(self.colliders, pin.radius)
        return _ProjectedRefiner(self.world, self._surface_object(owner), self.runtime, pin, rows, threshold)

    def _store_refined(self, alternate, row):
        value = _candidate_value(self.task, self.task.blocker if alternate else self.task.owner, row)
        if value is None and self.subdivision == 4: self.subdivision = 8; self.refiner = None; return
        if alternate: self.alternate = value or False
        else: self.current = value or False
        self.subdivision = 4; self.refiner = None

    def _finish_task(self):
        repair = _selected_repair(self.task, self.current, self.alternate)
        if repair is None: self.failures.append(FiberPinFailure(self.task, "No feasible attachment found."))
        else: self.repairs.append(repair)
        self.pin_index += 1; self.task = None; self.sampler = None; self.refiner = None

    def _surface(self, owner):
        self._ensure_surface(owner)
        return self.surfaces[owner][1]

    def _surface_object(self, owner):
        self._ensure_surface(owner)
        return self.surfaces[owner][0]

    def _ensure_surface(self, owner):
        if owner in self.surfaces: return
        obj = find_geometry_mesh_scp_obj(self.scene, self.root.name, owner)
        self.surfaces[owner] = (obj, build_mesh_surface_data(obj, self.depsgraph, {}) if obj else None)


def begin_fiber_pin_repair(root, scene, depsgraph, solver):
    return FiberPinRepairSession(root, scene, depsgraph, solver)


def repair_current_preflight_pins(root, scene, fiber, result, solver, depsgraph):
    snapshot = _binding_snapshot(fiber); context = _local_repair_context(root, scene, fiber, depsgraph)
    current, repaired = result, set()
    while current is not None and not current.valid:
        pin = _next_local_pin(fiber, current, repaired)
        if pin is None or not _repair_local_pin(context, fiber, pin):
            return _restore_local_repair(root, scene, fiber, snapshot, solver, depsgraph, result, repaired)
        repaired.add((pin.role, pin.index)); current = _repeat_preflight(root, scene, fiber, solver, depsgraph)
    if current is not None and current.valid and repaired: _refresh_local_repair_handles(root, scene, fiber)
    return current or _restore_local_repair(root, scene, fiber, snapshot, solver, depsgraph, result, repaired)


def _local_repair_context(root, scene, fiber, depsgraph):
    runtime = attachment_runtime(scene, depsgraph)
    sources = tuple(CollisionOracle(root, scene, depsgraph, float(fiber.collision_radius), .002).colliders())
    colliders = _capture_colliders(sources); key = ("pin-auto-repair", tuple(_source_key(row) for row in sources))
    return root, scene, depsgraph, runtime, colliders, _collision_world(colliders, key)


def _next_local_pin(fiber, result, repaired):
    for pin in _dedupe_pins(_invalid_pin_refs(fiber, result)):
        if (pin.role, pin.index) not in repaired: return pin
    return None


def _repair_local_pin(context, fiber, pin):
    candidate = _local_pin_candidate(context, pin)
    if candidate is None: return False
    with suppress_vcp_prop_updates():
        _set_pin(fiber, FiberPinRepair(pin, candidate, "LOCAL_SAME_OWNER", False))
    _invalidate_preflight(context[1], context[0], {fiber.id}); context[2].update()
    return True


def _local_pin_candidate(context, pin):
    obj, surface = _local_surface(context, pin.owner)
    threshold = _repair_threshold(context[4], pin.radius)
    valid = _first_valid_radial_rows(context, obj, pin, threshold)
    rows = _local_surface_rows(surface, pin) if not valid else ()
    valid = valid or _valid_rows_chunked(context[5], rows, pin.owner, threshold)
    refined = _refine_local_rows(context, obj, pin, valid)
    return _candidate_value(pin, pin.owner, refined)


def _local_surface(context, owner):
    obj = find_geometry_mesh_scp_obj(context[1], context[0].name, owner)
    surface = None if obj is None else build_mesh_surface_data(obj, context[2], context[3]["surface_cache"])
    return obj, surface


def _local_surface_rows(surface, pin):
    if not surface: return ()
    distance = _local_search_distance(pin); indices = _nearby_triangle_indices(surface, pin, distance)
    values = (_triangle_samples(surface, index, pin.offset, distance, pin.point) for index in indices)
    return _dedupe_candidate_rows(tuple(row for group in values for row in group))


def _first_valid_radial_rows(context, obj, pin, threshold):
    frame = resolve_surface_frame(obj, pin.raw, context[3]) if obj is not None else None
    if frame is None: return ()
    tangent = Vector(frame["tangent_world"]); bitangent = Vector(frame["normal_world"]).cross(tangent)
    for ratio in (.05, .1, .2, .35, .5, .75, 1.0):
        rows = _radial_ring_rows(context[3], obj, pin, frame["point_world"], tangent, bitangent, ratio)
        valid = _valid_rows(context[5], rows, pin.owner, threshold)
        if valid: return valid
    return ()


def _radial_ring_rows(runtime, obj, pin, origin, tangent, bitangent, ratio):
    radius = _local_search_distance(pin) * float(ratio)
    rows = (_radial_candidate(obj, runtime, origin, tangent, bitangent, radius, angle, pin.offset)
            for angle in range(24))
    return tuple(row for row in rows if row is not None)


def _radial_candidate(obj, runtime, origin, tangent, bitangent, radius, angle, offset):
    radians = tau * int(angle) / 24.0
    target = Vector(origin) + float(radius) * (cos(radians) * tangent + sin(radians) * bitangent)
    return _candidate_from_target(obj, runtime, target, offset)


def _dedupe_candidate_rows(rows):
    values = {}
    for row in rows: values.setdefault(str(row["raw"]), row)
    return tuple(values.values())


def _local_search_distance(pin):
    return auto_repair_search_distance(pin.radius)


def _nearby_triangle_indices(surface, pin, distance):
    hits = surface["bvh_world"].find_nearest_range(Vector(pin.point), distance + abs(float(pin.offset)))
    ranked = sorted(((float(row[3]), int(row[2])) for row in hits if row[2] is not None))
    attached = _attached_triangle_index(surface, pin.raw)
    values = ([attached] if attached is not None else []) + [index for _dist, index in ranked]
    return tuple(dict.fromkeys(values))[:128]


def _attached_triangle_index(surface, raw):
    from ..attachment_codec import fiber_surface_param
    param = fiber_surface_param(raw); target = () if param is None else tuple(param["tri_vidx"])
    return next((index for index, row in enumerate(surface["triangles"]) if tuple(row) == target), None)


def _triangle_samples(surface, index, offset, distance, source):
    triangle = tuple(int(value) for value in surface["triangles"][int(index)])
    rows = (_triangle_row(surface, triangle, weights, offset) for weights in _weights(4))
    origin, limit = Vector(source), float(distance)
    return tuple(row for row in rows if (Vector(row["point"]) - origin).length <= limit)


def _valid_rows_chunked(world, rows, owner, threshold):
    values = []
    for start in range(0, len(rows), 4096): values.extend(_valid_rows(world, rows[start:start + 4096], owner, threshold))
    return tuple(values)


def _refine_local_rows(context, obj, pin, rows):
    if obj is None or not rows: return None
    refiner = _ProjectedRefiner(context[5], obj, context[3], pin, rows,
                                _repair_threshold(context[4], pin.radius), (4, 12, 14))
    while not refiner.done: refiner.step()
    return refiner.result()


def _repeat_preflight(root, scene, fiber, solver, depsgraph):
    return preflight_fiber_hard_anchors(root, scene, fiber, solver, depsgraph, "FINAL")


def _refresh_local_repair_handles(root, scene, fiber):
    from ..visualization.fiber_sync import register_fiber_sync
    register_fiber_sync().refresh_selection(root=root, scene=scene,
                                            fiber_ids={fiber.id}, sync_handles=True)


def _restore_local_repair(root, scene, fiber, snapshot, solver, depsgraph, result, repaired):
    if not repaired: return result
    _restore_binding_snapshot(fiber, snapshot); _invalidate_preflight(scene, root, {fiber.id})
    depsgraph.update(); return _repeat_preflight(root, scene, fiber, solver, depsgraph)


def _yield_after_advance(phase, sampler, refiner, session):
    if phase == "PREFLIGHT": return True
    if sampler is not None or session.sampler is not None: return True
    return refiner is not None or session.refiner is not None


def apply_fiber_pin_repair_plan(root, scene, plan, solver, depsgraph):
    if plan.signature != fiber_pin_repair_signature(root, scene):
        return FiberPinRepairReport(0, 0, len(plan.repairs), ("STALE_PLAN",), ())
    groups = _repair_groups(plan.repairs); committed, failed, repaired = [], [], 0
    for fiber_id, rows in groups:
        fiber = _fiber_by_id(root, fiber_id); snapshot = _binding_snapshot(fiber)
        if fiber is None or not _apply_and_validate(root, scene, fiber, rows, solver, depsgraph):
            _rollback_repair(scene, root, fiber, snapshot, depsgraph); failed.append(fiber_id); continue
        committed.append(fiber_id); repaired += len(rows)
    _finish_repair_commit(root, scene, committed)
    unresolved = len(plan.failures) + sum(len(rows) for fid, rows in groups if fid in failed)
    return FiberPinRepairReport(repaired, len(committed), unresolved, tuple(failed), tuple(committed))


def _repair_groups(repairs):
    groups = {}
    for row in repairs: groups.setdefault(row.pin.fiber_id, []).append(row)
    return tuple((key, tuple(groups[key])) for key in sorted(groups))


def _apply_and_validate(root, scene, fiber, repairs, solver, depsgraph):
    with suppress_vcp_prop_updates():
        for repair in repairs: _set_pin(fiber, repair)
    _invalidate_preflight(scene, root, {fiber.id}); depsgraph.update()
    result = preflight_fiber_hard_anchors(root, scene, fiber, solver, depsgraph, "FINAL")
    return bool(result is not None and result.valid)


def _set_pin(fiber, repair):
    pin, candidate = repair.pin, repair.candidate
    if pin.role == "ENDPOINT_A": fiber.a_parent_id, fiber.a_attach_param = candidate.owner, candidate.raw
    elif pin.role == "ENDPOINT_B": fiber.b_parent_id, fiber.b_attach_param = candidate.owner, candidate.raw
    elif pin.role == "TOUCH": _set_item(fiber.mid_touches[pin.index - 1], candidate)
    else: _set_item(fiber.loop_anchors[pin.index], candidate)


def _set_item(item, candidate):
    item.parent_id, item.attach_param = candidate.owner, candidate.raw


def _binding_snapshot(fiber):
    if fiber is None: return None
    ends = (str(fiber.a_parent_id), str(fiber.a_attach_param), str(fiber.b_parent_id), str(fiber.b_attach_param))
    touches = tuple((str(row.parent_id), str(row.attach_param)) for row in fiber.mid_touches)
    loops = tuple((str(row.parent_id), str(row.attach_param)) for row in fiber.loop_anchors)
    return ends, touches, loops


def _restore_binding_snapshot(fiber, snapshot):
    if fiber is None or snapshot is None: return
    with suppress_vcp_prop_updates(): _restore_bindings(fiber, snapshot)


def _restore_bindings(fiber, snapshot):
    ends, touches, loops = snapshot
    fiber.a_parent_id, fiber.a_attach_param, fiber.b_parent_id, fiber.b_attach_param = ends
    for row, values in zip(fiber.mid_touches, touches): row.parent_id, row.attach_param = values
    for row, values in zip(fiber.loop_anchors, loops): row.parent_id, row.attach_param = values


def _rollback_repair(scene, root, fiber, snapshot, depsgraph):
    _restore_binding_snapshot(fiber, snapshot)
    if fiber is None: return
    _invalidate_preflight(scene, root, {fiber.id}); depsgraph.update()


def _finish_repair_commit(root, scene, fiber_ids):
    if not fiber_ids: return
    from ..visualization.fiber_cache_lifecycle import invalidate_fiber_caches
    from ..visualization.fiber_sync import register_fiber_sync
    invalidate_fiber_caches(scene, root, fiber_ids)
    register_fiber_sync().refresh_selection(root=root, scene=scene, fiber_ids=fiber_ids, sync_handles=True)


def _invalidate_preflight(scene, root, fiber_ids):
    from .fiber_anchor_preflight import invalidate_fiber_anchor_preflight
    invalidate_fiber_anchor_preflight(scene, root, fiber_ids)


def _fiber_by_id(root, fiber_id):
    return next((row for row in root.af_vcp_system.fibers if str(row.id) == str(fiber_id)), None)


def fiber_pin_repair_signature(root, scene):
    fibers = tuple(root.af_vcp_system.fibers)
    pins = tuple((str(row.id), _raw_anchor_specs(row)) for row in fibers)
    return _id_uid(scene), _id_uid(root), pins, _collider_probe_rows(root, scene)


def _repair_world(session):
    radius = max((float(row.collision_radius) for row in session.fibers), default=0.0)
    sources = tuple(CollisionOracle(session.root, session.scene, session.depsgraph, radius, .002).colliders())
    colliders = _capture_colliders(sources); key = ("pin-repair", tuple(_source_key(row) for row in sources))
    return _collision_world(colliders, key), colliders


def _invalid_pin_refs(fiber, result):
    if result is None or result.valid: return ()
    return tuple(_pin_ref(fiber, row) for row in result.violations)


def _pin_ref(fiber, violation):
    role = violation.role.value; index = int(violation.authored_index)
    owner, raw, offset = _pin_binding(fiber, role, index)
    return FiberPinRef(str(fiber.id), role, index, owner, raw, tuple(violation.point), offset,
                       float(fiber.collision_radius), str(violation.blocker_id), str(violation.relation))


def _pin_binding(fiber, role, index):
    if role == "ENDPOINT_A": return str(fiber.a_parent_id), str(fiber.a_attach_param), 0.0
    if role == "ENDPOINT_B": return str(fiber.b_parent_id), str(fiber.b_attach_param), 0.0
    if role == "TOUCH": return _item_binding(fiber.mid_touches[index - 1], True)
    return _item_binding(fiber.loop_anchors[index], False)


def _item_binding(item, touch):
    offset = float(item.normal_offset) if touch else 0.0
    return str(item.parent_id), str(item.attach_param), offset


def _dedupe_pins(rows):
    values = {}
    for row in rows:
        key = row.fiber_id, row.role, row.index
        current = values.get(key)
        if current is None or _pin_rank(row) < _pin_rank(current): values[key] = row
    return tuple(values[key] for key in sorted(values))


def _pin_rank(row):
    return (0 if row.relation == "UNRELATED" else 1, row.blocker, row.owner)


def _weights(count):
    for first in range(count + 1):
        for second in range(count + 1 - first):
            yield first / count, second / count, (count - first - second) / count


def _triangle_row(surface, triangle, weights, offset):
    abc = tuple(Vector(surface["verts_world"][index]) for index in triangle)
    normal = _triangle_normal(abc); point = sum((value * weight for value, weight in zip(abc, weights)), Vector())
    raw = encode_fiber_surface_param({"tri_vidx": triangle, "tri_weights": weights})
    return {"raw": raw, "surface": point, "point": point + normal * offset}


def _triangle_normal(abc):
    value = (abc[1] - abc[0]).cross(abc[2] - abc[0])
    return value.normalized() if value.length_squared > 1.0e-24 else Vector((0.0, 0.0, 1.0))


def _valid_rows(world, rows, owner, threshold):
    if not rows: return ()
    invalid = _invalid_indices(world, rows, owner, threshold)
    return tuple(row for index, row in enumerate(rows) if index not in invalid)


def _invalid_indices(world, rows, owner, threshold):
    points = np.asarray([row["point"] for row in rows], dtype=np.float64)
    edges = np.asarray([(index, index) for index in range(len(rows))], dtype=np.int64)
    owners = tuple(("", "") for _row in rows); skips = tuple(owner for _row in rows)
    batch = world.contact_pairs(points, edges, owners, 0.0, threshold, skip=skips)
    return {int(pair.edge) for pair in batch.pairs}


def _candidate_from_target(obj, runtime, target, offset):
    raw = capture_attachment_from_object(obj, Vector(target), runtime)
    frame = resolve_surface_frame(obj, raw, runtime) if raw else None
    if frame is None: return None
    point = frame["point_world"] + frame["normal_world"] * float(offset)
    return {"raw": raw, "surface": frame["point_world"], "point": point}


def _candidate_valid(world, row, owner, threshold):
    return not _invalid_indices(world, (row,), owner, threshold)


def _first_valid(rows, world, owner, threshold):
    packed = tuple((index, row) for index, row in enumerate(rows) if row is not None)
    if not packed: return None
    invalid = _invalid_indices(world, tuple(row for _index, row in packed), owner, threshold)
    return next(((index, row) for packed_index, (index, row) in enumerate(packed)
                 if packed_index not in invalid), None)


def _valid_flags(rows, world, owner, threshold):
    packed = tuple((index, row) for index, row in enumerate(rows) if row is not None)
    invalid = _invalid_indices(world, tuple(row for _index, row in packed), owner, threshold)
    valid_indices = {index for packed_index, (index, _row) in enumerate(packed) if packed_index not in invalid}
    return tuple(index in valid_indices for index in range(len(rows)))


def _update_interval(interval, candidate, valid):
    middle = 0.5 * (interval[1] + interval[2])
    if valid: interval[2], interval[3] = middle, candidate
    else: interval[1] = middle


def _candidate_key(pin, owner, subdivision, colliders):
    slack = _clearance_slack(colliders, pin.radius, "FINAL")
    return str(owner), float(pin.offset), float(pin.radius), float(slack), int(subdivision)


def _repair_threshold(colliders, radius):
    slack = _clearance_slack(colliders, radius, "FINAL")
    guard = serialization_guard(radius)
    return max(0.0, float(radius) - float(slack) + guard)


def _pin_with_owner(pin, owner):
    return FiberPinRef(pin.fiber_id, pin.role, pin.index, str(owner), pin.raw, pin.point,
                       pin.offset, pin.radius, pin.blocker, pin.relation)


def _candidate_value(pin, owner, row):
    if not row: return None
    point = tuple(float(value) for value in row["point"])
    distance = float((Vector(point) - Vector(pin.point)).length)
    return FiberPinCandidate(str(owner), str(row["raw"]), point, distance)


def _needs_alternate(pin, current):
    return pin.relation == "UNRELATED" and bool(current) and current.displacement > 5.0 * pin.radius


def _selected_repair(pin, current, alternate):
    if not current: return None
    transfer = use_owner_transfer(pin, current, alternate)
    candidate = alternate if transfer else current
    reason = "CLEAR_OUTLIER_TRANSFER" if transfer else "PRESERVE_OWNER"
    risky = bool(transfer or candidate.displacement > 5.0 * pin.radius)
    return FiberPinRepair(pin, candidate, reason, risky)


def _id_uid(value):
    try: return int(getattr(value, "session_uid", 0) or value.as_pointer())
    except Exception: return 0
