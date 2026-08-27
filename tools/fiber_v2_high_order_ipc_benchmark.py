"""Isolated cubic High-Order IPC representation benchmark for Fiber V2."""

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys
from statistics import median
from time import perf_counter

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v2_gcp_planar_dat_benchmark as gd
import fiber_v2_gcp_roadmap_benchmark as gcp
import fiber_v2_high_order_basis as hob
from anthroforge.core.vcp.v2.collision import cached_native_collision_world_batch


@dataclass(frozen=True)
class HighOrderConfig:
    stride: float
    force_ratio: float
    max_iterations: int
    seed_mode: str = "ROADMAP"
    proxy_subdivisions: int = 4
    dhat_radius_factor: float = 8.0
    trust_edge_factor: float = 0.75


@dataclass
class HighOrderStats(gcp.GcpStats):
    control_count: int = 0
    proxy_count: int = 0
    initial_fit_error: float = 0.0
    initial_proxy_valid: bool = False
    repaired_initial_valid: bool = False
    feasibility_iterations: int = 0
    initial_violation: float = 0.0
    repaired_violation: float = 0.0
    final_proxy_valid: bool = False
    final_output_valid: bool = False
    kappa: float = 0.0


@dataclass
class HighOrderModel:
    basis: hob.HighOrderBasis
    collision_basis: np.ndarray
    collision_pins: tuple
    mesh: object
    world: object
    potential: object
    static_vertices: np.ndarray
    structural: np.ndarray
    rhs: np.ndarray
    reference: np.ndarray
    free: np.ndarray
    settings: object
    pins: tuple
    dhat: float
    dmin: float
    kappa: float = 0.0


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--accepted-cap", type=int, default=120); parser.add_argument("--strides", default="1,2,3")
    parser.add_argument("--forces", default=".03,.1"); parser.add_argument("--proxy-subdivisions", type=int, default=4)
    parser.add_argument("--seed-modes", default="ROADMAP,SPAN_SQP")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _numbers(value, cast=float):
    return tuple(cast(row.strip()) for row in value.split(",") if row.strip())


def _configurations(args):
    modes = tuple(row.strip().upper() for row in args.seed_modes.split(",") if row.strip())
    return tuple(HighOrderConfig(stride, force, args.accepted_cap, mode, args.proxy_subdivisions)
        for mode in modes for stride in _numbers(args.strides)
        for force in _numbers(args.forces))


def _owner_vertices(snapshot, owner):
    rows = []
    for item in snapshot.collider_ranges:
        if str(item[1]) == str(owner): rows.extend(range(int(item[2]), int(item[2]) + int(item[3])))
    return rows


def _filter_entries(count, snapshot, request, collision_pins):
    entries = {(first, second): False for first in range(count) for second in range(first + 1, count)}
    anchors = tuple(request.anchors) * 2
    for pin, anchor in zip(collision_pins, anchors):
        nodes = range(max(0, pin - 1), min(count, pin + 2))
        for node in nodes:
            for vertex in _owner_vertices(snapshot, anchor.owner_id): entries[(node, count + vertex)] = False
    return entries


def _owner_filter(mesh, count, snapshot, request, collision_pins):
    values = _filter_entries(count, snapshot, request, collision_pins)
    mesh.can_collide = gcp.ipctk.make_static_obstacle_filter(count) & gcp.ipctk.make_sparse_filter(values, True)


def _collision_edges(basis):
    proxy = np.column_stack((np.arange(len(basis.proxy) - 1), np.arange(1, len(basis.proxy))))
    offset = len(basis.proxy); count = len(basis.output)
    output = np.column_stack((np.arange(count - 1), np.arange(1, count))) + offset
    return np.ascontiguousarray(np.vstack((proxy, output)), dtype=np.int32)


def _mesh(basis, collision_basis, collision_pins, snapshot, request):
    dynamic = collision_basis @ basis.controls; count = len(dynamic)
    surface = gcp._surface_edges(np.asarray(snapshot.triangles, dtype=np.int32)) + count
    edges = np.vstack((_collision_edges(basis), surface)); faces = np.asarray(snapshot.triangles) + count
    vertices = np.asfortranarray(np.vstack((dynamic, snapshot.vertices)), dtype=np.float64)
    edges = np.asfortranarray(edges, dtype=np.int32); faces = np.asfortranarray(faces, dtype=np.int32)
    mesh = gcp.ipctk.CollisionMesh(vertices, edges, faces)
    _owner_filter(mesh, count, snapshot, request, collision_pins)
    return mesh


def _free_coordinates(control_count, pinned):
    mask = np.ones(control_count, dtype=bool); mask[np.asarray(pinned, dtype=np.int64)] = False
    return np.flatnonzero(np.repeat(mask, 3))


def _model(request, snapshot, seed, direct, pins, config):
    basis = hob.build_high_order_basis(seed, pins, config.stride, config.proxy_subdivisions)
    collision_basis = np.vstack((basis.proxy, basis.output))
    collision_pins = basis.proxy_pins + tuple(len(basis.proxy) + index for index in pins)
    settings = request.settings
    matrix, rhs = hob.structural_system(basis, direct, settings, pins)
    dhat = config.dhat_radius_factor * request.collision_policy.collision_radius
    dmin = max(0.0, request.collision_policy.collision_radius - request.tolerances.clearance_slack)
    potential = gcp.ipctk.BarrierPotential(dhat, 1.0, True)
    world = cached_native_collision_world_batch(request.colliders)
    mesh = _mesh(basis, collision_basis, collision_pins, snapshot, request)
    return HighOrderModel(basis, collision_basis, collision_pins, mesh, world, potential,
        np.asarray(snapshot.vertices), matrix, rhs, direct,
        _free_coordinates(len(basis.controls), basis.pin_controls), settings, pins, dhat, dmin)


def _positions(model, controls):
    dynamic = model.collision_basis @ controls
    return np.asfortranarray(np.vstack((dynamic, model.static_vertices)), dtype=np.float64)


def _collisions(model, controls, stats):
    started = perf_counter(); rows = gcp.ipctk.NormalCollisions()
    rows.collision_set_type = gcp.ipctk.NormalCollisions.CollisionSetType.IPC
    rows.build(model.mesh, _positions(model, controls), model.dhat, model.dmin)
    stats.collision_build_ms += 1000.0 * (perf_counter() - started)
    stats.collision_total += len(rows)
    return rows


def _mapping(model):
    return gcp.sparse.kron(gcp.sparse.csr_matrix(model.collision_basis), gcp.sparse.eye(3), format="csr")


def _contact_system(model, controls, stats, derivatives=True):
    positions = _positions(model, controls); rows = _collisions(model, controls, stats)
    started = perf_counter(); energy = float(model.potential(rows, model.mesh, positions))
    if not derivatives:
        stats.derivatives_ms += 1000.0 * (perf_counter() - started); return energy, None, None
    gradient = np.asarray(model.potential.gradient(rows, model.mesh, positions)).reshape(-1)
    hessian = model.potential.hessian(rows, model.mesh, positions, gcp.ipctk.PSDProjectionMethod.CLAMP)
    mapping = _mapping(model); size = mapping.shape[0]
    result = mapping.T @ gradient[:size], mapping.T @ hessian[:size, :size].tocsr() @ mapping
    stats.derivatives_ms += 1000.0 * (perf_counter() - started)
    return energy, np.asarray(result[0]).reshape(-1), result[1].tocsr()


def _structural_gradient(model, controls):
    return (2.0 * (model.structural @ controls - model.rhs)).reshape(-1)


def _set_kappa(model, controls, contact, ratio):
    structural = _structural_gradient(model, controls)[model.free]; active = contact[model.free]
    scale = float(np.linalg.norm(active, np.inf))
    if scale > 1.0e-12:
        model.kappa = ratio * max(float(np.linalg.norm(structural, np.inf)), 1.0e-12) / scale


def _total_system(model, controls, stats, ratio):
    contact_e, contact_g, contact_h = _contact_system(model, controls, stats)
    if model.kappa == 0.0: _set_kappa(model, controls, contact_g, ratio)
    base = gcp.sparse.kron(2.0 * gcp.sparse.csr_matrix(model.structural), gcp.sparse.eye(3), format="csr")
    gradient = _structural_gradient(model, controls) + model.kappa * contact_g
    return _objective(model, controls, contact_e), gradient, base + model.kappa * contact_h


def _objective(model, controls, contact=None, stats=None):
    value = hob.structural_energy(controls, model.basis, model.reference, model.settings, model.pins)
    if contact is None: contact = _contact_system(model, controls, stats, False)[0]
    return float(value + model.kappa * contact)


def _direction(model, gradient, hessian, stats):
    started = perf_counter(); reduced = hessian[model.free][:, model.free]
    step = np.zeros(len(gradient)); step[model.free] = gcp.spsolve(reduced, -gradient[model.free])
    stats.linear_solve_ms += 1000.0 * (perf_counter() - started)
    return step.reshape((-1, 3))


def _trust_clip(model, controls, step, factor):
    movement = model.basis.proxy @ step; proxy = model.basis.proxy @ controls
    edge = float(np.mean(np.linalg.norm(np.diff(proxy, axis=0), axis=1)))
    limit = max(factor * edge, 1.0e-8); largest = float(np.max(np.linalg.norm(movement, axis=1)))
    return step * min(1.0, limit / max(largest, 1.0e-20))


def _owner_contacts(request, proxy_pins, count):
    rows = []
    for pin, anchor in zip(proxy_pins, request.anchors):
        intervals = tuple(item for item in ((pin - 1, 0., 1.) if pin else None,
            (pin, 0., 1.) if pin + 1 < count else None) if item is not None)
        if anchor.owner_id: rows.append(gcp.V2OwnerContact(anchor.owner_id, (pin,), intervals))
    return tuple(rows)


def _edge_owners(request, model, edges):
    anchors = tuple(request.anchors) * 2
    owners = {pin: anchor.owner_id for pin, anchor in zip(model.collision_pins, anchors)}
    return tuple((owners.get(first, ""), owners.get(second, "")) for first, second in edges)


def _owner_span(request, model, controls):
    points = model.collision_basis @ controls; edges = _collision_edges(model.basis); lengths = []
    for pin in model.collision_pins:
        for first, second in edges:
            if pin in (first, second): lengths.append(np.linalg.norm(points[first] - points[second]))
    radius = request.collision_policy.collision_radius
    return max(4.0 * request.tolerances.clearance_slack, 2.5 * radius, max(lengths, default=0.0), 1.0e-9)


def _contact_pairs(request, model, controls):
    points = model.collision_basis @ controls; edges = _collision_edges(model.basis)
    owners = _edge_owners(request, model, edges)
    radius = request.collision_policy.collision_radius
    activation = radius + max(4.0 * request.tolerances.clearance_slack, .25 * radius)
    return model.world.contact_pairs(points, edges, owners, _owner_span(request, model, controls), activation).pairs


def _pair_gap(pair, radius):
    return -(float(pair.distance) + radius) if pair.contained else float(pair.distance) - radius


def _maximum_violation(request, pairs):
    radius = request.collision_policy.collision_radius
    return max((max(0.0, -_pair_gap(row, radius)) for row in pairs), default=0.0)


def _repair_rows(request, model, pairs):
    radius = request.collision_policy.collision_radius; rows, rhs = [], []
    for pair in pairs:
        gap = _pair_gap(pair, radius)
        if gap >= -request.tolerances.clearance_slack: continue
        edge = _collision_edges(model.basis)[pair.edge]
        weight = (1.0 - pair.factor) * model.collision_basis[edge[0]]
        weight += pair.factor * model.collision_basis[edge[1]]
        rows.append(np.outer(weight, np.asarray(pair.normal)).reshape(-1))
        rhs.append(-gap + request.tolerances.clearance_slack)
    return np.asarray(rows), np.asarray(rhs)


def _repair_direction(request, model, controls, pairs):
    rows, rhs = _repair_rows(request, model, pairs)
    if not len(rows): return np.zeros_like(controls)
    reduced = rows[:, model.free]; gram = reduced @ reduced.T
    weights = np.linalg.lstsq(gram + 1.0e-10 * np.eye(len(gram)), rhs, rcond=1.0e-10)[0]
    result = np.zeros(controls.size); result[model.free] = reduced.T @ weights
    return result.reshape(controls.shape)


def _repair_trial(request, model, controls, direction, violation):
    movement = model.collision_basis @ direction
    limit = max(4.0 * request.collision_policy.collision_radius, 1.0e-7)
    direction *= min(1.0, limit / max(float(np.max(np.linalg.norm(movement, axis=1))), 1.0e-20))
    for scale in (1.0, .5, .25, .125, .0625):
        candidate = controls + scale * direction
        value = _maximum_violation(request, _contact_pairs(request, model, candidate))
        if value + request.tolerances.clearance_slack < violation: return candidate, value
    return controls, violation


def _repair_initial(request, model, controls, stats):
    pairs = _contact_pairs(request, model, controls); violation = _maximum_violation(request, pairs)
    stats.initial_violation = violation
    for _index in range(40):
        if violation <= request.tolerances.clearance_slack: break
        direction = _repair_direction(request, model, controls, pairs)
        candidate, value = _repair_trial(request, model, controls, direction, violation)
        stats.feasibility_iterations += 1
        if value >= violation: break
        controls, violation = candidate, value; pairs = _contact_pairs(request, model, controls)
    stats.repaired_violation = violation
    return controls


def _proxy_valid(request, snapshot, model, controls, stats):
    started = perf_counter(); points = model.basis.proxy @ controls
    contacts = _owner_contacts(request, model.basis.proxy_pins, len(points))
    row = gcp.validate_static_clearance(points, snapshot, request.collision_policy.collision_radius,
        contacts, slack=request.tolerances.clearance_slack)
    stats.validation_ms += 1000.0 * (perf_counter() - started)
    return bool(row.valid)


def _safe_step(request, snapshot, model, controls, target, stats):
    started = perf_counter(); source = model.basis.proxy @ controls; end = model.basis.proxy @ target
    contacts = _owner_contacts(request, model.basis.proxy_pins, len(source))
    row = gcp.collision_free_step(source, end, snapshot, request.collision_policy.collision_radius,
        contacts, slack=request.tolerances.clearance_slack, assume_initial_valid=True)
    output, output_end = model.basis.output @ controls, model.basis.output @ target
    other = gcp.collision_free_step(output, output_end, snapshot,
        request.collision_policy.collision_radius, gcp._contacts(request, len(output)),
        slack=request.tolerances.clearance_slack, assume_initial_valid=True)
    stats.ccd_ms += 1000.0 * (perf_counter() - started)
    return row if row.safe_step <= other.safe_step else other


def _trial(model, request, snapshot, controls, step, energy, stats):
    sweep = _safe_step(request, snapshot, model, controls, controls + step, stats)
    scale = min(1.0, .98 * max(0.0, sweep.safe_step))
    for _index in range(12):
        target = controls + scale * step; candidate = _objective(model, target, stats=stats)
        if scale > 1.0e-8 and np.isfinite(candidate) and candidate < energy:
            return target, candidate, scale
        scale *= .5
    return None, energy, 0.0


def _solve(request, snapshot, seed, direct, pins, config):
    stats = HighOrderStats(); model = _model(request, snapshot, seed, direct, pins, config)
    controls = model.basis.controls.copy(); _initialize_stats(stats, model, seed)
    stats.initial_proxy_valid = _proxy_valid(request, snapshot, model, controls, stats)
    if not stats.initial_proxy_valid: controls = _repair_initial(request, model, controls, stats)
    stats.repaired_initial_valid = _proxy_valid(request, snapshot, model, controls, stats)
    history = []
    if stats.repaired_initial_valid: controls, history = _iterations(model, request, snapshot, controls, config, stats)
    stats.kappa = model.kappa; stats.final_proxy_valid = _proxy_valid(request, snapshot, model, controls, stats)
    output = model.basis.output @ controls; stats.final_output_valid = gcp._valid(request, snapshot, output, stats)
    return output, controls, model.basis.proxy @ controls, stats, tuple(history), model.basis


def _initialize_stats(stats, model, seed):
    stats.control_count = len(model.basis.controls); stats.proxy_count = len(model.basis.proxy)
    fitted = model.basis.output @ model.basis.controls
    stats.initial_fit_error = float(np.max(np.linalg.norm(fitted - seed, axis=1)))


def _iterations(model, request, snapshot, controls, config, stats):
    history = []
    for _iteration in range(config.max_iterations):
        energy, gradient, hessian = _total_system(model, controls, stats, config.force_ratio)
        direction = _direction(model, gradient, hessian, stats)
        step = _trust_clip(model, controls, direction, config.trust_edge_factor)
        candidate, value, scale = _trial(model, request, snapshot, controls, step, energy, stats)
        stats.iterations += 1; history.append((energy, scale, float(np.max(np.linalg.norm(model.basis.proxy @ step, axis=1)))))
        if candidate is None: stats.rejected += 1; break
        stats.accepted += 1; controls = candidate
        if abs(energy - value) <= 1.0e-8 * max(1.0, abs(energy)): break
    return controls, history


def _timed(request, snapshot, planner, config, warm):
    started = perf_counter(); direct, pins = gcp._direct_reference(request)
    seed = warm if config.seed_mode == "SPAN_SQP" else gcp._planner_seed(planner, pins, len(direct))
    result = _solve(request, snapshot, seed, direct, pins, config)
    return 1000.0 * (perf_counter() - started), result, seed


def _timing(samples):
    values = tuple(row[0] for row in samples)
    return {"median_ms": median(values), "minimum_ms": min(values), "maximum_ms": max(values)}


def _variant(request, snapshot, planner, config, repeats, warm):
    samples = tuple(_timed(request, snapshot, planner, config, warm) for _ in range(max(1, repeats)))
    points, controls, proxy, stats, history, basis = samples[-1][1]
    return {"config": asdict(config), "timing": _timing(samples),
        "validated": bool(stats.final_proxy_valid and stats.final_output_valid),
        "points": points.tolist(), "proxy": proxy.tolist(), "seed": samples[-1][2].tolist(),
        "controls": controls.tolist(), "spans": basis.spans, "geometry": gcp._geometry(points),
        "stats": asdict(stats), "history": history}


def _name(config):
    return f"HO_IPC_{config.seed_mode}_S{config.stride:g}_F{config.force_ratio:g}"


def _payload(args, fiber, request, snapshot, planner, capture):
    baseline = gcp._baseline(request, snapshot, args.repeats)
    warm = np.asarray(baseline["result"]["points"], dtype=np.float64)
    variants = {_name(row): _variant(request, snapshot, planner, row, args.repeats, warm)
                for row in _configurations(args)}
    rows = [np.asarray(baseline["result"]["points"])] + [np.asarray(row["points"]) for row in variants.values()]
    for row in [baseline, *variants.values()]: gd._free_geometry(row, request)
    return {"file": bpy.data.filepath, "file_sha256": gcp.common._file_hash(bpy.data.filepath),
        "fiber": fiber.id, "capture_ms": capture, "node_count": request.settings.node_count,
        "radius": request.collision_policy.collision_radius, "planner_ms": planner.diagnostics.planner_ms,
        "baseline": baseline, "variants": variants, "nearby_triangles": gcp.p3._nearby(snapshot, rows)}


def main():
    args = _args(); fiber, request, snapshot, planner, capture = gcp._capture(args)
    record = _payload(args, fiber, request, snapshot, planner, capture); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    summary = {name: (round(row["timing"]["median_ms"], 1), row["validated"],
        round(row["geometry"]["worst_free_turn"], 1)) for name, row in record["variants"].items()}
    print("AF_V2_HIGH_ORDER_IPC", json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
