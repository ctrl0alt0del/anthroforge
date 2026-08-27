"""Compare corrected span-SQP with an isolated ROADMAP-seeded GCP contact model."""

import argparse
from dataclasses import asdict, dataclass, replace
import json
import os
from pathlib import Path
from statistics import median
import sys
from time import perf_counter

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
GCP_DEPS = ROOT / ".artifacts" / "gcp_deps"
sys.path.append(str(GCP_DEPS)); os.add_dll_directory(str(GCP_DEPS))
import ipctk
from scipy import sparse
from scipy.sparse.linalg import spsolve

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v2_production3_benchmark as p3
from anthroforge.core.vcp.v2.collision import V2OwnerContact, collision_free_step, validate_static_clearance
from anthroforge.core.vcp.v2.contact_core import _direct_reference, _planner_seed
from anthroforge.core.vcp.v2.planner import plan_reference_v43
from anthroforge.core.vcp.v2.structural import _static_settings, assemble_normal_matrix, static_fiber_energy
from anthroforge.core.vcp.v2.subfiber_sqp import _span_request, solve_subfiber_sqp_fixed
from anthroforge.tools import fiber_v2_planner_benchmark as common


@dataclass(frozen=True)
class GcpConfig:
    force_ratio: float
    max_iterations: int
    dhat_radius_factor: float = 8.0
    trust_edge_factor: float = 0.75


@dataclass
class GcpModel:
    mesh: object
    params: object
    potential: object
    static_vertices: np.ndarray
    structural: object
    settings: object
    q: np.ndarray
    free: np.ndarray
    kappa: float = 0.0


@dataclass
class GcpStats:
    iterations: int = 0
    accepted: int = 0
    rejected: int = 0
    collision_build_ms: float = 0.0
    derivatives_ms: float = 0.0
    linear_solve_ms: float = 0.0
    ccd_ms: float = 0.0
    validation_ms: float = 0.0
    candidate_total: int = 0
    collision_total: int = 0


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--accepted-cap", type=int, default=60)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _surface_edges(faces):
    rows = np.vstack((faces[:, (0, 1)], faces[:, (1, 2)], faces[:, (2, 0)]))
    return np.unique(np.sort(rows, axis=1), axis=0)


def _mesh_arrays(points, snapshot):
    count = len(points); chain = np.column_stack((np.arange(count - 1), np.arange(1, count)))
    surface = _surface_edges(np.asarray(snapshot.triangles, dtype=np.int32)) + count
    edges = np.vstack((chain, surface)); faces = np.asarray(snapshot.triangles) + count
    vertices = np.vstack((points, snapshot.vertices))
    return tuple(np.asfortranarray(row, dtype=dtype) for row, dtype in
                 ((vertices, np.float64), (edges, np.int32), (faces, np.int32)))


def _owner_vertices(snapshot, owner):
    rows = []
    for row in snapshot.collider_ranges:
        if str(row[1]) == str(owner): rows.extend(range(int(row[2]), int(row[2]) + int(row[3])))
    return rows


def _filter_map(count, snapshot, owners):
    blocked = {(i, j): False for i in range(count) for j in range(i + 1, count)}
    for nodes, owner in owners:
        if not owner: continue
        for node in nodes:
            for vertex in _owner_vertices(snapshot, owner): blocked[(node, count + vertex)] = False
    return blocked


def _owner_filter(mesh, count, snapshot, request):
    owners = (((0, min(1, count - 1)), request.anchors[0].owner_id),
              ((max(0, count - 2), count - 1), request.anchors[-1].owner_id))
    sparse_filter = ipctk.make_sparse_filter(_filter_map(count, snapshot, owners), True)
    mesh.can_collide = ipctk.make_static_obstacle_filter(count) & sparse_filter


def _model(request, snapshot, seed, direct, config):
    vertices, edges, faces = _mesh_arrays(seed, snapshot)
    mesh = ipctk.CollisionMesh(vertices, edges, faces); _owner_filter(mesh, len(seed), snapshot, request)
    radius = request.collision_policy.collision_radius
    params = ipctk.SmoothContactParameters(config.dhat_radius_factor * radius, .5, 0., .1, 0., 2)
    settings = _static_settings(request.settings); matrix = assemble_normal_matrix(len(seed), settings)
    free = np.arange(3, 3 * (len(seed) - 1), dtype=np.int64)
    return GcpModel(mesh, params, ipctk.SmoothPotential(params), snapshot.vertices,
                    matrix, settings, direct, free)


def _positions(model, points):
    return np.asfortranarray(np.vstack((points, model.static_vertices)), dtype=np.float64)


def _collisions(model, points, stats):
    started = perf_counter(); rows = ipctk.SmoothCollisions()
    rows.build(model.mesh, _positions(model, points), model.params, False)
    stats.collision_build_ms += 1000.0 * (perf_counter() - started)
    stats.candidate_total += int(rows.n_candidates()); stats.collision_total += len(rows)
    return rows


def _structural_gradient(model, points):
    return (2.0 * (model.structural @ points - model.settings.rho * model.q)).reshape(-1)


def _derivatives(model, points, stats):
    collisions = _collisions(model, points, stats); positions = _positions(model, points)
    started = perf_counter(); energy = float(model.potential(collisions, model.mesh, positions))
    gradient = np.asarray(model.potential.gradient(collisions, model.mesh, positions)).reshape(-1)
    hessian = model.potential.hessian(collisions, model.mesh, positions, ipctk.PSDProjectionMethod.CLAMP)
    stats.derivatives_ms += 1000.0 * (perf_counter() - started)
    return energy, gradient[:3 * len(points)], hessian[:3 * len(points), :3 * len(points)].tocsr()


def _set_kappa(model, points, contact_gradient, ratio):
    structural = _structural_gradient(model, points)[model.free]
    contact = contact_gradient[model.free]
    contact_norm = float(np.linalg.norm(contact, np.inf))
    if contact_norm <= 1.0e-12: return
    model.kappa = ratio * max(float(np.linalg.norm(structural, np.inf)), 1.0e-12) / contact_norm


def _total_system(model, points, stats, ratio):
    energy, contact_g, contact_h = _derivatives(model, points, stats)
    if model.kappa == 0.0: _set_kappa(model, points, contact_g, ratio)
    base_h = sparse.kron(2.0 * sparse.csr_matrix(model.structural), sparse.eye(3), format="csr")
    gradient = _structural_gradient(model, points) + model.kappa * contact_g
    hessian = base_h + model.kappa * contact_h
    return _objective(model, points, energy), gradient, hessian


def _objective(model, points, contact_energy=None, stats=None):
    structural = static_fiber_energy(points, model.q, model.settings).total
    if contact_energy is None: contact_energy = _contact_energy(model, points, stats)
    return float(structural + model.kappa * contact_energy)


def _contact_energy(model, points, stats):
    collisions = _collisions(model, points, stats); started = perf_counter()
    result = float(model.potential(collisions, model.mesh, _positions(model, points)))
    stats.derivatives_ms += 1000.0 * (perf_counter() - started)
    return result


def _direction(model, gradient, hessian, stats):
    started = perf_counter(); reduced = hessian[model.free][:, model.free]
    step = np.zeros(len(gradient)); step[model.free] = spsolve(reduced, -gradient[model.free])
    stats.linear_solve_ms += 1000.0 * (perf_counter() - started)
    return step.reshape(-1, 3)


def _trust_clip(step, points, factor):
    edge = float(np.mean(np.linalg.norm(np.diff(points, axis=0), axis=1)))
    limit = max(factor * edge, 1.0e-8); largest = float(np.max(np.linalg.norm(step, axis=1)))
    return step * min(1.0, limit / max(largest, 1.0e-20))


def _contacts(request, count):
    rows = []
    _direct, indices = _direct_reference(request)
    for index, anchor in zip(indices, request.anchors):
        intervals = tuple(row for row in ((index - 1, 0., 1.) if index else None,
                          (index, 0., 1.) if index + 1 < count else None) if row is not None)
        if anchor.owner_id: rows.append(V2OwnerContact(anchor.owner_id, (index,), intervals))
    return tuple(rows)


def _safe_step(request, snapshot, points, target, stats):
    started = perf_counter(); radius = request.collision_policy.collision_radius
    result = collision_free_step(points, target, snapshot, radius, _contacts(request, len(points)),
                                 slack=request.tolerances.clearance_slack, assume_initial_valid=True)
    stats.ccd_ms += 1000.0 * (perf_counter() - started)
    return result


def _valid(request, snapshot, points, stats):
    started = perf_counter(); radius = request.collision_policy.collision_radius
    row = validate_static_clearance(points, snapshot, radius, _contacts(request, len(points)),
                                    slack=request.tolerances.clearance_slack)
    stats.validation_ms += 1000.0 * (perf_counter() - started)
    return row.valid


def _trial(model, request, snapshot, points, step, energy, stats):
    sweep = _safe_step(request, snapshot, points, points + step, stats)
    scale = min(1.0, .98 * max(0.0, sweep.safe_step))
    for _index in range(12):
        target = points + scale * step
        if scale > 1.0e-8:
            candidate = _objective(model, target, stats=stats)
            if np.isfinite(candidate) and candidate < energy: return target, candidate, scale
        scale *= .5
    return None, energy, 0.0


def _span_solve(request, snapshot, seed, direct, config):
    stats = GcpStats(); model = _model(request, snapshot, seed, direct, config)
    points = np.asarray(seed, dtype=np.float64).copy(); history = []
    for iteration in range(config.max_iterations):
        energy, gradient, hessian = _total_system(model, points, stats, config.force_ratio)
        step = _trust_clip(_direction(model, gradient, hessian, stats), points, config.trust_edge_factor)
        candidate, candidate_energy, scale = _trial(model, request, snapshot, points, step, energy, stats)
        stats.iterations += 1; history.append((energy, scale, float(np.max(np.linalg.norm(step, axis=1)))))
        if candidate is None: stats.rejected += 1; break
        stats.accepted += 1; points = candidate
        if abs(energy - candidate_energy) <= 1.0e-8 * max(1.0, abs(energy)): break
    return points, stats, tuple(history), model.kappa


def _span_cap(total, first, last, count):
    raw = total * (last - first) / max(1, count - 1)
    return max(2, int(round(raw)))


def _gcp_solve(request, snapshot, planner, config):
    direct, indices = _direct_reference(request); seed = _planner_seed(planner, indices, len(direct))
    if not _valid(request, snapshot, seed, GcpStats()): raise RuntimeError("ROADMAP seed is not clearance-valid")
    rows = []; stats = []; histories = []; kappas = []
    for span, (first, last) in enumerate(zip(indices[:-1], indices[1:])):
        sub = _span_request(request, seed, span, first, last, True)
        cap = _span_cap(config.max_iterations, first, last, len(seed)); sub_config = replace(config, max_iterations=cap)
        points, trace, history, kappa = _span_solve(sub, snapshot, seed[first:last + 1], direct[first:last + 1], sub_config)
        rows.extend(points if not rows else points[1:]); stats.append(trace); histories.append(history); kappas.append(kappa)
    return np.asarray(rows), stats, histories, kappas, seed


def _stats_sum(rows):
    result = GcpStats()
    for row in rows:
        for name in vars(result): setattr(result, name, getattr(result, name) + getattr(row, name))
    return asdict(result)


def _turns(points):
    before = points[1:-1] - points[:-2]; after = points[2:] - points[1:-1]
    scale = np.linalg.norm(before, axis=1) * np.linalg.norm(after, axis=1)
    cosine = np.divide(np.sum(before * after, axis=1), scale, out=np.ones(len(scale)), where=scale > 1e-20)
    return np.r_[0.0, np.degrees(np.arccos(np.clip(cosine, -1., 1.))), 0.0]


def _geometry(points):
    values = np.asarray(points); turns = _turns(values); lengths = np.linalg.norm(np.diff(values, axis=0), axis=1)
    return {"path_length": float(np.sum(lengths)), "max_turn": float(np.max(turns)),
            "max_turn_node": int(np.argmax(turns)), "node10_turn": float(turns[10]),
            "segment_cv": float(np.std(lengths) / max(np.mean(lengths), 1.0e-12)),
            "turns": tuple(map(float, turns))}


def _timed_gcp(request, snapshot, planner, config):
    started = perf_counter(); planner = plan_reference_v43(request, snapshot)
    result = _gcp_solve(request, snapshot, planner, config); validation = GcpStats()
    valid = _valid(request, snapshot, result[0], validation)
    return 1000.0 * (perf_counter() - started), result, valid, validation.validation_ms


def _gcp_variant(request, snapshot, planner, config, repeats):
    samples = [_timed_gcp(request, snapshot, planner, config) for _index in range(max(1, repeats))]
    points, rows, histories, kappas, seed = samples[-1][1]
    return {"config": asdict(config), "timing": _timing(samples), "validated": samples[-1][2],
            "points": points.tolist(), "seed": seed.tolist(), "geometry": _geometry(points),
            "stats": _stats_sum(rows), "final_validation_ms": samples[-1][3],
            "histories": histories, "kappas": kappas}


def _timing(samples):
    values = [row[0] for row in samples]
    return {"median_ms": median(values), "minimum_ms": min(values), "maximum_ms": max(values)}


def _baseline(request, snapshot, repeats):
    samples = []
    for _index in range(max(1, repeats)):
        started = perf_counter(); package = solve_subfiber_sqp_fixed(request, snapshot=snapshot)
        samples.append((1000.0 * (perf_counter() - started), package))
    package = samples[-1][1]
    return {"timing": _timing(samples), "result": p3._result(package),
            "geometry": _geometry(np.asarray(package.result.points))}


def _capture(args):
    root = common._root(); fiber = common._fiber(root, args.fiber_id)
    request, snapshot, capture = p3._capture(root, fiber, bpy.context.evaluated_depsgraph_get())
    request = p3._override_cap(request, args.accepted_cap)
    planner = plan_reference_v43(request, snapshot)
    return fiber, request, snapshot, planner, capture


def _payload(args, fiber, request, snapshot, planner, capture):
    configs = tuple(GcpConfig(value, args.accepted_cap) for value in (.03, .1, .3, 1.0))
    baseline = _baseline(request, snapshot, args.repeats)
    variants = {f"GCP_{row.force_ratio:g}": _gcp_variant(request, snapshot, planner, row, args.repeats) for row in configs}
    routes = [np.asarray(baseline["result"]["points"])] + [np.asarray(row["points"]) for row in variants.values()]
    return {"file": bpy.data.filepath, "file_sha256": common._file_hash(bpy.data.filepath),
            "fiber": fiber.id, "capture_ms": capture, "node_count": request.settings.node_count,
            "radius": request.collision_policy.collision_radius, "planner_ms": planner.diagnostics.planner_ms,
            "planner_succeeded": planner.succeeded, "baseline": baseline, "variants": variants,
            "nearby_triangles": p3._nearby(snapshot, routes)}


def main():
    args = _args(); fiber, request, snapshot, planner, capture = _capture(args)
    record = _payload(args, fiber, request, snapshot, planner, capture)
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    summary = {name: (round(row["timing"]["median_ms"], 2), row["validated"],
        round(row["geometry"]["node10_turn"], 2)) for name, row in record["variants"].items()}
    print("AF_V2_GCP_ROADMAP", json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
