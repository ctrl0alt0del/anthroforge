"""Compare span-SQP, GCP, and GCP plus the official Planar-DAT filter."""

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


@dataclass(frozen=True)
class DatConfig:
    force_ratio: float
    max_iterations: int
    dhat_radius_factor: float = 8.0
    trust_edge_factor: float = 0.75
    relaxation: float = 0.9
    subdivisions: int = 4


@dataclass
class DatState:
    trust: object
    collisions: object
    mesh: object
    static_vertices: np.ndarray
    subdivisions: int
    dhat: float


@dataclass
class DatStats(gcp.GcpStats):
    dat_update_ms: float = 0.0
    dat_filter_ms: float = 0.0
    limited_nodes: int = 0
    audit_failures: int = 0
    minimum_node_ratio: float = 1.0
    contractions: int = 0


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--accepted-cap", type=int, default=60); parser.add_argument("--force", type=float, default=.1)
    parser.add_argument("--dhat", default="8"); parser.add_argument("--relaxation", default=".5,.75,.9,.98")
    parser.add_argument("--subdivisions", type=int, default=4)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _numbers(value):
    return tuple(float(row.strip()) for row in value.split(",") if row.strip())


def _normal_collisions():
    rows = gcp.ipctk.NormalCollisions()
    rows.collision_set_type = gcp.ipctk.NormalCollisions.CollisionSetType.OGC
    return rows


def _clearance(request):
    return request.collision_policy.collision_radius + request.tolerances.clearance_slack


def _proxy(points, subdivisions):
    weights = np.arange(subdivisions, dtype=np.float64) / subdivisions
    rows = ((1.0 - weights)[None, :, None] * points[:-1, None] + weights[None, :, None] * points[1:, None])
    return np.vstack((rows.reshape(-1, 3), points[-1]))


def _dat_mesh(points, snapshot, request, subdivisions):
    samples = _proxy(points, subdivisions); vertices, edges, faces = gcp._mesh_arrays(samples, snapshot)
    mesh = gcp.ipctk.CollisionMesh(vertices, edges, faces)
    gcp._owner_filter(mesh, len(samples), snapshot, request)
    return mesh, np.asarray(snapshot.vertices), samples


def _dat_positions(state, points):
    return np.asfortranarray(np.vstack((_proxy(points, state.subdivisions), state.static_vertices)))


def _dat_state(snapshot, request, points, config, stats):
    mesh, static, samples = _dat_mesh(points, snapshot, request, config.subdivisions)
    trust = gcp.ipctk.ogc.TrustRegion(config.dhat_radius_factor * request.collision_policy.collision_radius)
    trust.relaxed_radius_scaling = config.relaxation; collisions = _normal_collisions()
    positions = np.asfortranarray(np.vstack((samples, static))); started = perf_counter()
    trust.update(mesh, positions, collisions, _clearance(request))
    stats.dat_update_ms += 1000.0 * (perf_counter() - started)
    return DatState(trust, collisions, mesh, static, config.subdivisions,
                    config.dhat_radius_factor * request.collision_policy.collision_radius)


def _refresh(state, request, points, step, stats):
    motion = float(np.max(np.linalg.norm(_proxy(step, state.subdivisions), axis=1)))
    state.trust.trust_region_inflation_radius = max(2.0 * state.dhat, motion + _clearance(request))
    started = perf_counter(); state.trust.update(state.mesh, _dat_positions(state, points), state.collisions,
                                                 _clearance(request))
    stats.dat_update_ms += 1000.0 * (perf_counter() - started)


def _ratios(before, after):
    old = np.linalg.norm(before, axis=1); new = np.linalg.norm(after, axis=1)
    return np.divide(new, old, out=np.ones_like(new), where=old > 1.0e-15)


def _node_ratios(sample_ratios, count, subdivisions):
    edges = np.array([np.min(sample_ratios[i*subdivisions:(i+1)*subdivisions+1]) for i in range(count - 1)])
    nodes = np.ones(count); nodes[:-1] = np.minimum(nodes[:-1], edges); nodes[1:] = np.minimum(nodes[1:], edges)
    return nodes


def _filter(state, points, step, stats):
    samples = _proxy(points, state.subdivisions); sampled_step = _proxy(step, state.subdivisions)
    full = np.zeros_like(_dat_positions(state, points)); full[:len(samples)] = sampled_step
    started = perf_counter(); state.trust.planar_filter_step(state.mesh, _dat_positions(state, points), full)
    stats.dat_filter_ms += 1000.0 * (perf_counter() - started)
    sample_ratios = _ratios(sampled_step, full[:len(samples)])
    ratios = _node_ratios(sample_ratios, len(points), state.subdivisions); result = step * ratios[:, None]
    stats.limited_nodes += int(np.count_nonzero(ratios < 1.0 - 1.0e-10))
    stats.minimum_node_ratio = min(stats.minimum_node_ratio, float(np.min(ratios)))
    return result, ratios


def _audit(request, snapshot, points, step, stats):
    row = gcp._safe_step(request, snapshot, points, points + step, stats)
    safe = float(row.safe_step) >= 1.0 - 1.0e-12
    stats.audit_failures += int(not safe)
    return safe, float(row.safe_step)


def _line_search(model, points, step, energy, stats):
    scale = 1.0
    for _index in range(12):
        target = points + scale * step; candidate = gcp._objective(model, target, stats=stats)
        if np.isfinite(candidate) and candidate < energy: return target, candidate, scale
        scale *= .5
    return None, energy, 0.0


def _dat_trial(model, request, snapshot, points, step, energy, stats):
    safe, fraction = _audit(request, snapshot, points, step, stats)
    if not safe: return None, energy, 0.0, fraction
    candidate, value, scale = _line_search(model, points, step, energy, stats)
    return candidate, value, scale, fraction


def _attempt(state, model, request, snapshot, points, direction, energy, factor, stats):
    raw = gcp._trust_clip(direction, points, factor); _refresh(state, request, points, raw, stats)
    step, ratios = _filter(state, points, raw, stats)
    candidate, value, scale, safe = _dat_trial(model, request, snapshot, points, step, energy, stats)
    return candidate, value, (energy, scale, safe, float(np.min(ratios)), factor)


def _contracted_step(state, model, request, snapshot, points, direction, energy, config, stats):
    history = []
    for retry in range(8):
        factor = config.trust_edge_factor * (0.5 ** retry)
        candidate, value, row = _attempt(state, model, request, snapshot, points, direction, energy, factor, stats)
        stats.iterations += 1; history.append(row)
        if candidate is not None: return candidate, value, tuple(history)
        stats.rejected += 1; stats.contractions += 1
    return None, energy, tuple(history)


def _span_solve(request, snapshot, seed, direct, config):
    stats = DatStats(); model = gcp._model(request, snapshot, seed, direct, config)
    points = np.asarray(seed, dtype=np.float64).copy(); state = _dat_state(snapshot, request, points, config, stats); history = []
    for _iteration in range(config.max_iterations):
        energy, gradient, hessian = gcp._total_system(model, points, stats, config.force_ratio)
        direction = gcp._direction(model, gradient, hessian, stats)
        candidate, value, attempts = _contracted_step(state, model, request, snapshot, points, direction,
                                                       energy, config, stats)
        history.extend(attempts)
        if candidate is None: break
        stats.accepted += 1; points = candidate
        if abs(energy - value) <= 1.0e-8 * max(1.0, abs(energy)): break
    return points, stats, tuple(history), model.kappa


def _dat_solve(request, snapshot, planner, config):
    direct, indices = gcp._direct_reference(request); seed = gcp._planner_seed(planner, indices, len(direct))
    if not gcp._valid(request, snapshot, seed, DatStats()): raise RuntimeError("ROADMAP seed is not clearance-valid")
    rows, stats, histories, kappas = [], [], [], []
    for span, (first, last) in enumerate(zip(indices[:-1], indices[1:])):
        sub = gcp._span_request(request, seed, span, first, last, True)
        cap = gcp._span_cap(config.max_iterations, first, last, len(seed)); cfg = replace(config, max_iterations=cap)
        points, trace, history, kappa = _span_solve(sub, snapshot, seed[first:last + 1], direct[first:last + 1], cfg)
        rows.extend(points if not rows else points[1:]); stats.append(trace); histories.append(history); kappas.append(kappa)
    return np.asarray(rows), stats, histories, kappas, seed


def _timed_dat(request, snapshot, planner, config):
    started = perf_counter(); planner = gcp.plan_reference_v43(request, snapshot)
    result = _dat_solve(request, snapshot, planner, config); validation = DatStats()
    valid = gcp._valid(request, snapshot, result[0], validation)
    return 1000.0 * (perf_counter() - started), result, valid, validation.validation_ms


def _timing(samples):
    values = [row[0] for row in samples]
    return {"median_ms": median(values), "minimum_ms": min(values), "maximum_ms": max(values)}


def _stats_sum(rows):
    result = DatStats()
    for row in rows:
        for name in vars(result): setattr(result, name, getattr(result, name) + getattr(row, name))
    result.minimum_node_ratio = min(row.minimum_node_ratio for row in rows)
    return asdict(result)


def _variant(request, snapshot, planner, config, repeats):
    samples = [_timed_dat(request, snapshot, planner, config) for _index in range(max(1, repeats))]
    points, rows, histories, kappas, seed = samples[-1][1]
    return {"config": asdict(config), "timing": _timing(samples), "validated": samples[-1][2],
            "points": points.tolist(), "seed": seed.tolist(), "geometry": gcp._geometry(points),
            "stats": _stats_sum(rows), "final_validation_ms": samples[-1][3],
            "histories": histories, "kappas": kappas}


def _configs(args):
    return tuple(DatConfig(args.force, args.accepted_cap, dhat_radius_factor=dhat, relaxation=relax,
                           subdivisions=args.subdivisions)
                 for dhat in _numbers(args.dhat) for relax in _numbers(args.relaxation))


def _name(config):
    return f"GCP_DAT_F{config.force_ratio:g}_H{config.dhat_radius_factor:g}_R{config.relaxation:g}"


def _free_geometry(row, request):
    turns = np.asarray(row["geometry"]["turns"]); _direct, pins = gcp._direct_reference(request)
    mask = np.ones(len(turns), dtype=bool); mask[np.asarray(pins, dtype=np.int64)] = False
    index = int(np.argmax(np.where(mask, turns, -1.0)))
    row["geometry"].update({"worst_free_turn": float(turns[index]), "worst_free_node": index})


def _payload(args, fiber, request, snapshot, planner, capture):
    base = gcp._baseline(request, snapshot, args.repeats)
    cfg = gcp.GcpConfig(args.force, args.accepted_cap, _numbers(args.dhat)[0])
    plain = gcp._gcp_variant(request, snapshot, planner, cfg, args.repeats)
    variants = {_name(row): _variant(request, snapshot, planner, row, args.repeats) for row in _configs(args)}
    rows = [np.asarray(base["result"]["points"]), np.asarray(plain["points"])] + [np.asarray(v["points"]) for v in variants.values()]
    for row in [base, plain, *variants.values()]: _free_geometry(row, request)
    return {"file": bpy.data.filepath, "file_sha256": gcp.common._file_hash(bpy.data.filepath), "fiber": fiber.id,
            "capture_ms": capture, "node_count": request.settings.node_count, "radius": request.collision_policy.collision_radius,
            "planner_ms": planner.diagnostics.planner_ms, "baseline": base, "gcp": plain, "variants": variants,
            "nearby_triangles": gcp.p3._nearby(snapshot, rows)}


def main():
    args = _args(); fiber, request, snapshot, planner, capture = gcp._capture(args)
    record = _payload(args, fiber, request, snapshot, planner, capture); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    summary = {name: (round(row["timing"]["median_ms"], 2), row["validated"],
        round(row["geometry"]["worst_free_turn"], 2)) for name, row in record["variants"].items()}
    print("AF_V2_GCP_PLANAR_DAT", json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
