"""Compare OGC with isotropic and Planar-DAT trust filters on Fiber."""

import argparse
from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
import sys
from statistics import median
from time import perf_counter

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v2_gcp_roadmap_benchmark as gcp
import fiber_v2_gcp_planar_dat_benchmark as gd


@dataclass(frozen=True)
class OgcConfig:
    force_ratio: float
    max_iterations: int
    filter_kind: str
    dhat_radius_factor: float = 8.0
    trust_edge_factor: float = 0.75
    relaxation: float = 0.9
    subdivisions: int = 8


@dataclass
class OgcModel:
    mesh: object
    static_vertices: np.ndarray
    mapping: object
    barrier: object
    structural: object
    settings: object
    q: np.ndarray
    free: np.ndarray
    dhat: float
    dmin: float
    kappa: float = 0.0


@dataclass
class OgcStats(gcp.GcpStats):
    trust_update_ms: float = 0.0
    trust_filter_ms: float = 0.0
    limited_nodes: int = 0
    audit_failures: int = 0
    contractions: int = 0
    minimum_node_ratio: float = 1.0


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--accepted-cap", type=int, default=120); parser.add_argument("--force", default=".03,.1,.3")
    parser.add_argument("--dhat", default="4,8,16"); parser.add_argument("--relaxation", default=".75,.9")
    parser.add_argument("--subdivisions", type=int, default=8); parser.add_argument("--filters", default="isotropic,planar")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _mapping(count, subdivisions):
    rows, cols, data = [], [], []
    for edge in range(count - 1):
        for local in range(subdivisions):
            row = edge * subdivisions + local; weight = local / subdivisions
            rows.extend((row, row)); cols.extend((edge, edge + 1)); data.extend((1.0 - weight, weight))
    rows.append((count - 1) * subdivisions); cols.append(count - 1); data.append(1.0)
    scalar = gcp.sparse.csr_matrix((data, (rows, cols)), shape=((count - 1) * subdivisions + 1, count))
    return gcp.sparse.kron(scalar, gcp.sparse.eye(3), format="csr")


def _dmin(request):
    radius = request.collision_policy.collision_radius
    return max(0.0, radius - request.tolerances.clearance_slack)


def _model(request, snapshot, seed, direct, config):
    samples = gd._proxy(seed, config.subdivisions); vertices, edges, faces = gcp._mesh_arrays(samples, snapshot)
    mesh = gcp.ipctk.CollisionMesh(vertices, edges, faces); gcp._owner_filter(mesh, len(samples), snapshot, request)
    radius = request.collision_policy.collision_radius; dhat = config.dhat_radius_factor * radius
    settings = gcp._static_settings(request.settings); matrix = gcp.assemble_normal_matrix(len(seed), settings)
    free = np.arange(3, 3 * (len(seed) - 1), dtype=np.int64)
    barrier = gcp.ipctk.BarrierPotential(dhat, 1.0, True)
    return OgcModel(mesh, np.asarray(snapshot.vertices), _mapping(len(seed), config.subdivisions), barrier,
                    matrix, settings, direct, free, dhat, _dmin(request))


def _positions(model, points, subdivisions):
    samples = gd._proxy(points, subdivisions)
    return np.asfortranarray(np.vstack((samples, model.static_vertices)), dtype=np.float64)


def _collisions(model, positions, stats):
    started = perf_counter(); rows = gcp.ipctk.NormalCollisions()
    rows.use_area_weighting = True; rows.collision_set_type = gcp.ipctk.NormalCollisions.CollisionSetType.OGC
    rows.build(model.mesh, positions, model.dhat, model.dmin)
    stats.collision_build_ms += 1000.0 * (perf_counter() - started); stats.collision_total += len(rows)
    return rows


def _contact(model, points, subdivisions, stats, derivatives):
    positions = _positions(model, points, subdivisions); collisions = _collisions(model, positions, stats)
    started = perf_counter(); energy = float(model.barrier(collisions, model.mesh, positions))
    if not derivatives: stats.derivatives_ms += 1000.0 * (perf_counter() - started); return energy, None, None
    gradient = np.asarray(model.barrier.gradient(collisions, model.mesh, positions)).reshape(-1)
    hessian = model.barrier.hessian(collisions, model.mesh, positions, gcp.ipctk.PSDProjectionMethod.CLAMP)
    size = model.mapping.shape[0]; gradient = model.mapping.T @ gradient[:size]
    hessian = model.mapping.T @ hessian[:size, :size].tocsr() @ model.mapping
    stats.derivatives_ms += 1000.0 * (perf_counter() - started)
    return energy, np.asarray(gradient).reshape(-1), hessian.tocsr()


def _structural_gradient(model, points):
    return (2.0 * (model.structural @ points - model.settings.rho * model.q)).reshape(-1)


def _set_kappa(model, points, contact_gradient, ratio):
    structural = _structural_gradient(model, points)[model.free]; contact = contact_gradient[model.free]
    scale = float(np.linalg.norm(contact, np.inf))
    if scale > 1.0e-12: model.kappa = ratio * max(float(np.linalg.norm(structural, np.inf)), 1.0e-12) / scale


def _system(model, points, config, stats):
    energy, contact_g, contact_h = _contact(model, points, config.subdivisions, stats, True)
    if model.kappa == 0.0: _set_kappa(model, points, contact_g, config.force_ratio)
    base = gcp.sparse.kron(2.0 * gcp.sparse.csr_matrix(model.structural), gcp.sparse.eye(3), format="csr")
    gradient = _structural_gradient(model, points) + model.kappa * contact_g
    hessian = base + model.kappa * contact_h
    return _objective(model, points, config, stats, energy), gradient, hessian


def _objective(model, points, config, stats, contact_energy=None):
    structural = gcp.static_fiber_energy(points, model.q, model.settings).total
    if contact_energy is None: contact_energy = _contact(model, points, config.subdivisions, stats, False)[0]
    return float(structural + model.kappa * contact_energy)


def _direction(model, gradient, hessian, stats):
    started = perf_counter(); reduced = hessian[model.free][:, model.free]
    step = np.zeros(len(gradient)); step[model.free] = gcp.spsolve(reduced, -gradient[model.free])
    stats.linear_solve_ms += 1000.0 * (perf_counter() - started)
    return step.reshape(-1, 3)


def _state(model, config, points, stats):
    trust = gcp.ipctk.ogc.TrustRegion(model.dhat); trust.relaxed_radius_scaling = config.relaxation
    collisions = gcp.ipctk.NormalCollisions(); collisions.collision_set_type = gcp.ipctk.NormalCollisions.CollisionSetType.OGC
    state = gd.DatState(trust, collisions, model.mesh, model.static_vertices, config.subdivisions, model.dhat)
    _refresh(state, model, config, points, config.trust_edge_factor, stats)
    return state


def _refresh(state, model, config, points, factor, stats):
    edge = float(np.mean(np.linalg.norm(np.diff(points, axis=0), axis=1)))
    state.trust.trust_region_inflation_radius = max(2.0 * model.dhat, factor * edge + model.dmin)
    started = perf_counter(); state.trust.update(state.mesh, gd._dat_positions(state, points), state.collisions, model.dmin)
    stats.trust_update_ms += 1000.0 * (perf_counter() - started)


def _filter(state, points, step, config, stats):
    samples = gd._proxy(points, state.subdivisions); sampled = gd._proxy(step, state.subdivisions)
    full = np.zeros_like(gd._dat_positions(state, points)); full[:len(samples)] = sampled
    started = perf_counter(); method = state.trust.planar_filter_step if config.filter_kind == "planar" else state.trust.filter_step
    method(state.mesh, gd._dat_positions(state, points), full)
    stats.trust_filter_ms += 1000.0 * (perf_counter() - started)
    sample_ratios = gd._ratios(sampled, full[:len(samples)])
    ratios = gd._node_ratios(sample_ratios, len(points), state.subdivisions)
    stats.limited_nodes += int(np.count_nonzero(ratios < 1.0 - 1.0e-10))
    stats.minimum_node_ratio = min(stats.minimum_node_ratio, float(np.min(ratios)))
    return step * ratios[:, None], ratios


def _audit(request, snapshot, points, step, stats):
    row = gcp._safe_step(request, snapshot, points, points + step, stats); fraction = float(row.safe_step)
    safe = fraction >= 1.0 - 1.0e-12; stats.audit_failures += int(not safe)
    return safe, fraction


def _line_search(model, points, step, energy, config, stats):
    scale = 1.0
    for _index in range(12):
        target = points + scale * step; value = _objective(model, target, config, stats)
        if np.isfinite(value) and value < energy: return target, value, scale
        scale *= .5
    return None, energy, 0.0


def _attempt(state, model, request, snapshot, points, direction, energy, config, factor, stats):
    raw = gcp._trust_clip(direction, points, factor); _refresh(state, model, config, points, factor, stats)
    step, ratios = _filter(state, points, raw, config, stats); safe, fraction = _audit(request, snapshot, points, step, stats)
    if not safe: return None, energy, (energy, 0.0, fraction, float(np.min(ratios)), factor)
    candidate, value, scale = _line_search(model, points, step, energy, config, stats)
    return candidate, value, (energy, scale, fraction, float(np.min(ratios)), factor)


def _contracted(state, model, request, snapshot, points, direction, energy, config, stats):
    history = []
    for retry in range(8):
        factor = config.trust_edge_factor * (0.5 ** retry)
        candidate, value, row = _attempt(state, model, request, snapshot, points, direction, energy, config, factor, stats)
        stats.iterations += 1; history.append(row)
        if candidate is not None: return candidate, value, tuple(history)
        stats.rejected += 1; stats.contractions += 1
    return None, energy, tuple(history)


def _span(request, snapshot, seed, direct, config):
    stats = OgcStats(); model = _model(request, snapshot, seed, direct, config)
    points = np.asarray(seed).copy(); state = _state(model, config, points, stats); history = []
    for _iteration in range(config.max_iterations):
        energy, gradient, hessian = _system(model, points, config, stats)
        direction = _direction(model, gradient, hessian, stats)
        candidate, value, attempts = _contracted(state, model, request, snapshot, points, direction, energy, config, stats)
        history.extend(attempts)
        if candidate is None: break
        stats.accepted += 1; points = candidate
        if abs(energy - value) <= 1.0e-8 * max(1.0, abs(energy)): break
    return points, stats, tuple(history), model.kappa


def _solve(request, snapshot, planner, config):
    direct, indices = gcp._direct_reference(request); seed = gcp._planner_seed(planner, indices, len(direct))
    if not gcp._valid(request, snapshot, seed, OgcStats()): raise RuntimeError("ROADMAP seed is not clearance-valid")
    rows, stats, histories, kappas = [], [], [], []
    for span, (first, last) in enumerate(zip(indices[:-1], indices[1:])):
        sub = gcp._span_request(request, seed, span, first, last, True)
        cap = gcp._span_cap(config.max_iterations, first, last, len(seed)); cfg = replace(config, max_iterations=cap)
        points, trace, history, kappa = _span(sub, snapshot, seed[first:last + 1], direct[first:last + 1], cfg)
        rows.extend(points if not rows else points[1:]); stats.append(trace); histories.append(history); kappas.append(kappa)
    return np.asarray(rows), stats, histories, kappas, seed


def _stats_sum(rows):
    result = OgcStats()
    for row in rows:
        for name in vars(result): setattr(result, name, getattr(result, name) + getattr(row, name))
    result.minimum_node_ratio = min(row.minimum_node_ratio for row in rows)
    return asdict(result)


def _timed(request, snapshot, config):
    started = perf_counter(); planner = gcp.plan_reference_v43(request, snapshot)
    result = _solve(request, snapshot, planner, config); validation = OgcStats()
    valid = gcp._valid(request, snapshot, result[0], validation)
    return 1000.0 * (perf_counter() - started), result, valid, validation.validation_ms


def _variant(request, snapshot, config, repeats):
    samples = [_timed(request, snapshot, config) for _index in range(max(1, repeats))]
    points, rows, histories, kappas, seed = samples[-1][1]; values = [row[0] for row in samples]
    timing = {"median_ms": median(values), "minimum_ms": min(values), "maximum_ms": max(values)}
    return {"config": asdict(config), "timing": timing, "validated": samples[-1][2], "points": points.tolist(),
            "seed": seed.tolist(), "geometry": gcp._geometry(points), "stats": _stats_sum(rows),
            "final_validation_ms": samples[-1][3], "histories": histories, "kappas": kappas}


def _configs(args):
    return tuple(OgcConfig(force, args.accepted_cap, kind, dhat, relaxation=relax, subdivisions=args.subdivisions)
                 for force in gd._numbers(args.force) for dhat in gd._numbers(args.dhat)
                 for relax in gd._numbers(args.relaxation) for kind in args.filters.split(","))


def _name(config):
    return f"OGC_{config.filter_kind.upper()}_F{config.force_ratio:g}_H{config.dhat_radius_factor:g}_R{config.relaxation:g}"


def _payload(args, fiber, request, snapshot, planner, capture):
    baseline = gcp._baseline(request, snapshot, args.repeats)
    gcfg = gcp.GcpConfig(.1, args.accepted_cap, gd._numbers(args.dhat)[0]); reference = gcp._gcp_variant(request, snapshot, planner, gcfg, args.repeats)
    variants = {_name(row): _variant(request, snapshot, row, args.repeats) for row in _configs(args)}
    routes = [np.asarray(baseline["result"]["points"]), np.asarray(reference["points"])] + [np.asarray(v["points"]) for v in variants.values()]
    for row in [baseline, reference, *variants.values()]: gd._free_geometry(row, request)
    return {"file": bpy.data.filepath, "file_sha256": gcp.common._file_hash(bpy.data.filepath), "fiber": fiber.id,
            "capture_ms": capture, "node_count": request.settings.node_count, "radius": request.collision_policy.collision_radius,
            "planner_ms": planner.diagnostics.planner_ms, "baseline": baseline, "gcp": reference, "variants": variants,
            "nearby_triangles": gcp.p3._nearby(snapshot, routes)}


def main():
    args = _args(); fiber, request, snapshot, planner, capture = gcp._capture(args)
    record = _payload(args, fiber, request, snapshot, planner, capture); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    summary = {name: (round(row["timing"]["median_ms"], 1), row["validated"],
        round(row["geometry"]["worst_free_turn"], 1)) for name, row in record["variants"].items()}
    print("AF_V2_OGC_DAT", json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
