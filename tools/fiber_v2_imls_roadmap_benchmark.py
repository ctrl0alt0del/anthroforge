"""Compare corrected span-SQP with a finite-clearance IMLS contact experiment."""

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
DEPS = ROOT / ".artifacts" / "gcp_deps"
sys.path.append(str(DEPS)); os.add_dll_directory(str(DEPS))
from scipy import sparse
from scipy.spatial import cKDTree
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
class ImlsConfig:
    force_ratio: float
    max_iterations: int
    bandwidth_factor: float = 2.5
    neighbor_count: int = 24
    trust_edge_factor: float = .75


@dataclass(frozen=True)
class ImlsCollider:
    collider_id: str
    owner_id: str
    points: np.ndarray
    normals: np.ndarray
    tree: object
    bandwidth: float


@dataclass
class ImlsModel:
    colliders: tuple
    structural: object
    settings: object
    q: np.ndarray
    free: np.ndarray
    activation: float
    kappa: float = 0.0


@dataclass
class ImlsStats:
    iterations: int = 0
    accepted: int = 0
    rejected: int = 0
    query_ms: float = 0.0
    assembly_ms: float = 0.0
    linear_solve_ms: float = 0.0
    ccd_ms: float = 0.0
    validation_ms: float = 0.0
    sample_queries: int = 0
    active_samples: int = 0


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--accepted-cap", type=int, default=60)
    parser.add_argument("--force-ratio", type=float); parser.add_argument("--bandwidth-factor", type=float)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _face_normals(points, faces):
    first = points[faces[:, 1]] - points[faces[:, 0]]
    second = points[faces[:, 2]] - points[faces[:, 0]]
    return np.cross(first, second)


def _oriented_face_normals(points, faces):
    normals = _face_normals(points, faces)
    volume = np.sum(np.einsum("ij,ij->i", points[faces[:, 0]], normals)) / 6.0
    return -normals if volume < 0.0 else normals


def _vertex_normals(points, faces):
    face_normals = _oriented_face_normals(points, faces); normals = np.zeros_like(points)
    for corner in range(3): np.add.at(normals, faces[:, corner], face_normals)
    lengths = np.linalg.norm(normals, axis=1)
    return normals / np.maximum(lengths[:, None], 1.0e-20)


def _spacing(points, faces):
    edges = np.vstack((faces[:, (0, 1)], faces[:, (1, 2)], faces[:, (2, 0)]))
    edges = np.unique(np.sort(edges, axis=1), axis=0)
    lengths = np.linalg.norm(points[edges[:, 1]] - points[edges[:, 0]], axis=1)
    return max(float(np.median(lengths)), 1.0e-8)


def _sample_barycentrics():
    return np.asarray(((1/3, 1/3, 1/3), (.6, .2, .2), (.2, .6, .2), (.2, .2, .6),
                       (.45, .45, .1), (.45, .1, .45), (.1, .45, .45)), dtype=np.float64)


def _face_samples(points, faces):
    triangles = points[faces]; bary = _sample_barycentrics()
    samples = np.einsum("bk,fkj->fbj", bary, triangles).reshape(-1, 3)
    normals = _oriented_face_normals(points, faces)
    normals /= np.maximum(np.linalg.norm(normals, axis=1)[:, None], 1.0e-20)
    return samples, np.repeat(normals, len(bary), axis=0)


def _sample_spacing(points):
    tree = cKDTree(points); distances, _indices = tree.query(points, k=2)
    return max(float(np.median(distances[:, 1])), 1.0e-8)


def _collider(snapshot, row, config):
    offset, count, face_offset, face_count = map(int, row[2:6])
    points = np.asarray(snapshot.vertices[offset:offset + count], dtype=np.float64)
    faces = np.asarray(snapshot.triangles[face_offset:face_offset + face_count], dtype=np.int64) - offset
    samples, normals = _face_samples(points, faces)
    bandwidth = config.bandwidth_factor * _sample_spacing(samples)
    return ImlsCollider(str(row[0]), str(row[1]), samples, normals,
                        cKDTree(samples), bandwidth)


def _colliders(snapshot, config):
    return tuple(_collider(snapshot, row, config) for row in snapshot.collider_ranges)


def _model(request, snapshot, direct, config):
    settings = _static_settings(request.settings)
    matrix = assemble_normal_matrix(len(direct), settings)
    free = np.arange(3, 3 * (len(direct) - 1), dtype=np.int64)
    radius = request.collision_policy.collision_radius
    slack = request.tolerances.clearance_slack
    activation = radius + max(4.0 * slack, .25 * radius)
    return ImlsModel(_colliders(snapshot, config), matrix, settings, direct, free, activation)


def _field(collider, point, neighbors, stats):
    started = perf_counter(); count = min(int(neighbors), len(collider.points))
    distances, indices = collider.tree.query(point, k=count)
    stats.query_ms += 1000.0 * (perf_counter() - started); stats.sample_queries += 1
    points = collider.points[np.atleast_1d(indices)]; normals = collider.normals[np.atleast_1d(indices)]
    delta = np.asarray(point) - points; weights = np.exp(-np.sum(delta * delta, axis=1) / collider.bandwidth ** 2)
    planes = np.einsum("ij,ij->i", normals, delta); total = max(float(np.sum(weights)), 1.0e-30)
    value = float(np.dot(weights, planes) / total)
    weight_grad = (-2.0 / collider.bandwidth ** 2) * weights[:, None] * delta
    numerator_grad = np.sum(weight_grad * planes[:, None] + weights[:, None] * normals, axis=0)
    gradient = (numerator_grad - value * np.sum(weight_grad, axis=0)) / total
    return value, gradient


def _exempt(request, edge, count, collider):
    if edge == 0 and request.anchors[0].owner_id == collider.owner_id: return True
    return edge == count - 2 and request.anchors[-1].owner_id == collider.owner_id


def _sample_rows(points):
    for edge, (first, second) in enumerate(zip(points[:-1], points[1:])):
        for factor in (.25, .5, .75):
            yield edge, factor, (1.0 - factor) * first + factor * second


def _contact_rows(model, request, points, config, stats):
    rows = []
    for edge, factor, point in _sample_rows(points):
        for collider in model.colliders:
            if _exempt(request, edge, len(points), collider): continue
            value, gradient = _field(collider, point, config.neighbor_count, stats)
            residual = model.activation - value
            if residual > 0.0: rows.append((edge, factor, residual, gradient))
    stats.active_samples += len(rows)
    return tuple(rows)


def _assemble_contact(count, rows, stats):
    started = perf_counter(); gradient = np.zeros((count, 3)); matrix = sparse.lil_matrix((3 * count, 3 * count))
    energy = 0.0
    for edge, factor, residual, normal in rows:
        energy += .5 * residual ** 2; _add_gradient(gradient, edge, factor, residual, normal)
        _add_hessian(matrix, edge, factor, normal)
    stats.assembly_ms += 1000.0 * (perf_counter() - started)
    return energy, gradient.reshape(-1), matrix.tocsr()


def _add_gradient(output, edge, factor, residual, normal):
    output[edge] -= (1.0 - factor) * residual * normal
    output[edge + 1] -= factor * residual * normal


def _add_hessian(output, edge, factor, normal):
    block = np.outer(normal, normal); weights = (1.0 - factor, factor)
    for local_a, weight_a in enumerate(weights):
        for local_b, weight_b in enumerate(weights):
            a, b = 3 * (edge + local_a), 3 * (edge + local_b)
            output[a:a + 3, b:b + 3] += weight_a * weight_b * block


def _structural_gradient(model, points):
    value = model.structural @ points - model.settings.rho * model.q
    return (2.0 * value).reshape(-1)


def _set_kappa(model, structural, contact, ratio):
    contact_norm = float(np.linalg.norm(contact[model.free], np.inf))
    if contact_norm <= 1.0e-12: return
    structural_norm = max(float(np.linalg.norm(structural[model.free], np.inf)), 1.0e-12)
    model.kappa = ratio * structural_norm / contact_norm


def _system(model, request, points, config, stats):
    rows = _contact_rows(model, request, points, config, stats)
    contact_e, contact_g, contact_h = _assemble_contact(len(points), rows, stats)
    structural_g = _structural_gradient(model, points)
    if model.kappa == 0.0: _set_kappa(model, structural_g, contact_g, config.force_ratio)
    base_h = sparse.kron(2.0 * sparse.csr_matrix(model.structural), sparse.eye(3), format="csr")
    energy = static_fiber_energy(points, model.q, model.settings).total + model.kappa * contact_e
    return float(energy), structural_g + model.kappa * contact_g, base_h + model.kappa * contact_h


def _contact_energy(model, request, points, config, stats):
    rows = _contact_rows(model, request, points, config, stats)
    return .5 * sum(row[2] ** 2 for row in rows)


def _objective(model, request, points, config, stats):
    structural = static_fiber_energy(points, model.q, model.settings).total
    return float(structural + model.kappa * _contact_energy(model, request, points, config, stats))


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
    rows = []; _direct, indices = _direct_reference(request)
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


def _trial(model, request, snapshot, points, step, energy, config, stats):
    sweep = _safe_step(request, snapshot, points, points + step, stats)
    scale = min(1.0, .98 * max(0.0, sweep.safe_step))
    for _index in range(12):
        target = points + scale * step
        candidate = _objective(model, request, target, config, stats)
        if scale > 1.0e-8 and np.isfinite(candidate) and candidate < energy:
            return target, candidate, scale
        scale *= .5
    return None, energy, 0.0


def _span_solve(request, snapshot, seed, direct, config):
    stats = ImlsStats(); model = _model(request, snapshot, direct, config)
    points = np.asarray(seed, dtype=np.float64).copy(); history = []
    for _iteration in range(config.max_iterations):
        energy, gradient, hessian = _system(model, request, points, config, stats)
        step = _trust_clip(_direction(model, gradient, hessian, stats), points, config.trust_edge_factor)
        candidate, new_energy, scale = _trial(model, request, snapshot, points, step, energy, config, stats)
        stats.iterations += 1; history.append((energy, scale, float(np.max(np.linalg.norm(step, axis=1)))))
        if candidate is None: stats.rejected += 1; break
        stats.accepted += 1; points = candidate
        if abs(energy - new_energy) <= 1.0e-8 * max(1.0, abs(energy)): break
    return points, stats, tuple(history), model.kappa


def _span_cap(total, first, last, count):
    return max(2, int(round(total * (last - first) / max(1, count - 1))))


def _imls_solve(request, snapshot, planner, config):
    direct, indices = _direct_reference(request); seed = _planner_seed(planner, indices, len(direct))
    if not _valid(request, snapshot, seed, ImlsStats()): raise RuntimeError("ROADMAP seed is not clearance-valid")
    rows, stats, histories, kappas = [], [], [], []
    for span, (first, last) in enumerate(zip(indices[:-1], indices[1:])):
        sub = _span_request(request, seed, span, first, last, True)
        local = replace(config, max_iterations=_span_cap(config.max_iterations, first, last, len(seed)))
        points, trace, history, kappa = _span_solve(sub, snapshot, seed[first:last + 1], direct[first:last + 1], local)
        rows.extend(points if not rows else points[1:]); stats.append(trace); histories.append(history); kappas.append(kappa)
    return np.asarray(rows), stats, histories, kappas, seed, indices


def _stats_sum(rows):
    result = ImlsStats()
    for row in rows:
        for name in vars(result): setattr(result, name, getattr(result, name) + getattr(row, name))
    return asdict(result)


def _turns(points):
    before = points[1:-1] - points[:-2]; after = points[2:] - points[1:-1]
    scale = np.linalg.norm(before, axis=1) * np.linalg.norm(after, axis=1)
    cosine = np.divide(np.sum(before * after, axis=1), scale, out=np.ones(len(scale)), where=scale > 1.0e-20)
    return np.r_[0.0, np.degrees(np.arccos(np.clip(cosine, -1., 1.))), 0.0]


def _geometry(points, pins):
    values = np.asarray(points); turns = _turns(values); lengths = np.linalg.norm(np.diff(values, axis=0), axis=1)
    free = tuple(index for index in range(1, len(values) - 1) if index not in set(pins))
    worst = max(free, key=lambda index: turns[index])
    return {"path_length": float(np.sum(lengths)), "worst_free_turn": float(turns[worst]),
            "worst_free_node": int(worst), "node8_turn": float(turns[8]),
            "node10_turn": float(turns[10]), "node59_turn": float(turns[59]),
            "segment_cv": float(np.std(lengths) / max(np.mean(lengths), 1.0e-12)),
            "turns": tuple(map(float, turns))}


def _timed_imls(request, snapshot, config):
    started = perf_counter(); planner = plan_reference_v43(request, snapshot)
    result = _imls_solve(request, snapshot, planner, config); validation = ImlsStats()
    valid = _valid(request, snapshot, result[0], validation)
    return 1000.0 * (perf_counter() - started), result, valid, validation.validation_ms


def _timing(samples):
    values = [row[0] for row in samples]
    return {"median_ms": median(values), "minimum_ms": min(values), "maximum_ms": max(values)}


def _variant(request, snapshot, config, repeats):
    samples = [_timed_imls(request, snapshot, config) for _index in range(max(1, repeats))]
    points, rows, histories, kappas, seed, pins = samples[-1][1]
    return {"config": asdict(config), "timing": _timing(samples), "validated": samples[-1][2],
            "points": points.tolist(), "seed": seed.tolist(), "geometry": _geometry(points, pins),
            "stats": _stats_sum(rows), "final_validation_ms": samples[-1][3],
            "histories": histories, "kappas": kappas}


def _baseline(request, snapshot, repeats):
    samples = []
    for _index in range(max(1, repeats)):
        started = perf_counter(); package = solve_subfiber_sqp_fixed(request, snapshot=snapshot)
        samples.append((1000.0 * (perf_counter() - started), package))
    package = samples[-1][1]; _direct, pins = _direct_reference(request)
    return {"timing": _timing(samples), "result": p3._result(package),
            "geometry": _geometry(np.asarray(package.result.points), pins)}


def _capture(args):
    root = common._root(); fiber = common._fiber(root, args.fiber_id)
    request, snapshot, capture = p3._capture(root, fiber, bpy.context.evaluated_depsgraph_get())
    return fiber, p3._override_cap(request, args.accepted_cap), snapshot, capture


def _payload(args, fiber, request, snapshot, capture):
    configs = _configs(args)
    baseline = _baseline(request, snapshot, args.repeats)
    variants = {_variant_name(row): _variant(request, snapshot, row, args.repeats) for row in configs}
    routes = [np.asarray(baseline["result"]["points"])] + [np.asarray(row["points"]) for row in variants.values()]
    return {"file": bpy.data.filepath, "file_sha256": common._file_hash(bpy.data.filepath),
            "fiber": fiber.id, "capture_ms": capture, "node_count": request.settings.node_count,
            "radius": request.collision_policy.collision_radius, "baseline": baseline,
            "variants": variants, "nearby_triangles": p3._nearby(snapshot, routes)}


def _variant_name(config):
    return f"IMLS_F{config.force_ratio:g}_H{config.bandwidth_factor:g}"


def _configs(args):
    if args.force_ratio is not None or args.bandwidth_factor is not None:
        return (ImlsConfig(args.force_ratio or .1, args.accepted_cap,
                           args.bandwidth_factor or 2.5),)
    rows = tuple(ImlsConfig(value, args.accepted_cap) for value in (.03, .1, .3, 1.0))
    return rows + tuple(ImlsConfig(.1, args.accepted_cap, value) for value in (.75, 1.25, 4.0))


def main():
    args = _args(); fiber, request, snapshot, capture = _capture(args)
    record = _payload(args, fiber, request, snapshot, capture)
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    summary = {name: (round(row["timing"]["median_ms"], 2), row["validated"],
        round(row["geometry"]["worst_free_turn"], 2), row["geometry"]["worst_free_node"])
        for name, row in record["variants"].items()}
    print("AF_V2_IMLS_ROADMAP", json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
