"""Read-only first/second-order optimality diagnostic for corrected span-SQP."""

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from time import perf_counter

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEPS = ROOT / ".artifacts" / "gcp_deps"
sys.path.append(str(DEPS)); os.add_dll_directory(str(DEPS))
from scipy.optimize import nnls

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v2_production3_benchmark as p3
from anthroforge.core.vcp.v2.collision import (V2OwnerContact,
    cached_native_collision_world_batch, collision_free_step, segment_triangle_distances,
    validate_static_clearance)
from anthroforge.core.vcp.v2.contact_core import _direct_reference
from anthroforge.core.vcp.v2.structural import (_normal_gradient, _static_settings,
    assemble_normal_matrix, static_fiber_energy)
from anthroforge.core.vcp.v2.subfiber_sqp import _span_request, solve_subfiber_sqp_fixed
from anthroforge.tools import fiber_v2_planner_benchmark as common


@dataclass(frozen=True)
class SpanModel:
    first: int
    last: int
    reference: np.ndarray
    settings: object
    owners: tuple


@dataclass(frozen=True)
class ContactModel:
    span: int
    edge: int
    collider: str
    face: int
    factor: float
    gap: float
    normal: np.ndarray
    triangle: np.ndarray
    contained: bool


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--accepted-cap", type=int, default=120)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _span_models(request, seed):
    _direct, indices = _direct_reference(request); rows = []
    for span, (first, last) in enumerate(zip(indices[:-1], indices[1:])):
        sub = _span_request(request, seed, span, first, last, True)
        reference, _pins = _direct_reference(sub)
        owners = sub.anchors[0].owner_id, sub.anchors[-1].owner_id
        rows.append(SpanModel(first, last, reference, _static_settings(sub.settings), owners))
    return tuple(rows), tuple(map(int, indices))


def _energy(spans, points):
    return float(sum(static_fiber_energy(points[row.first:row.last + 1], row.reference,
        row.settings).total for row in spans))


def _gradient(spans, points):
    output = np.zeros_like(points)
    for row in spans:
        block = points[row.first:row.last + 1]
        output[row.first:row.last + 1] += 2.0 * _normal_gradient(block, row.reference, row.settings)
    return output.reshape(-1)


def _objective_hessian(spans, count):
    output = np.zeros((3 * count, 3 * count)); eye = np.eye(3)
    for row in spans:
        indices = np.arange(3 * row.first, 3 * (row.last + 1))
        block = 2.0 * np.kron(assemble_normal_matrix(row.last - row.first + 1, row.settings), eye)
        output[np.ix_(indices, indices)] += block
    return output


def _free_dofs(count, pins):
    mask = np.ones((count, 3), dtype=bool); mask[list(pins)] = False
    return np.flatnonzero(mask.reshape(-1))


def _fd_objective_gradient(spans, points, dofs, step):
    flat = points.reshape(-1); result = np.empty(len(dofs))
    for output, index in enumerate(dofs):
        plus, minus = flat.copy(), flat.copy(); plus[index] += step; minus[index] -= step
        result[output] = (_energy(spans, plus.reshape((-1, 3))) -
                          _energy(spans, minus.reshape((-1, 3)))) / (2.0 * step)
    return result


def _relative_error(first, second):
    scale = max(1.0, float(np.linalg.norm(first)), float(np.linalg.norm(second)))
    return float(np.linalg.norm(np.asarray(first) - np.asarray(second)) / scale)


def _objective_check(spans, points, free, steps):
    exact = _gradient(spans, points)[free]; rows = []
    for step in steps:
        numeric = _fd_objective_gradient(spans, points, free, step)
        rows.append({"step": step, "relative_error": _relative_error(exact, numeric),
                     "maximum_error": float(np.max(np.abs(exact - numeric)))})
    return {"energy": _energy(spans, points), "analytic_norm": float(np.linalg.norm(exact)), "samples": rows,
            "best_relative_error": min(row["relative_error"] for row in rows)}


def _owner_span(request, points, pins):
    lengths = []
    for pin in pins:
        if pin: lengths.append(np.linalg.norm(points[pin] - points[pin - 1]))
        if pin + 1 < len(points): lengths.append(np.linalg.norm(points[pin + 1] - points[pin]))
    radius = request.collision_policy.collision_radius; slack = request.tolerances.clearance_slack
    return max(4.0 * slack, 2.5 * radius, max(lengths, default=0.0), 1.0e-9)


def _edge_rows(count):
    return tuple((index, index + 1) for index in range(count - 1))


def _edge_owners(count, owners):
    return tuple((owners[0] if index == 0 else "", owners[1] if index + 2 == count else "")
                 for index in range(count - 1))


def _contact_triangle(snapshot, pair):
    row = snapshot.collider_ranges[pair.instance]; face = int(row[4]) + int(pair.face)
    return face, np.asarray(snapshot.vertices[snapshot.triangles[face]], dtype=np.float64)


def _contact_model(span, first, pair, snapshot, radius):
    face, triangle = _contact_triangle(snapshot, pair)
    gap = -(pair.distance + radius) if pair.contained else pair.distance - radius
    return ContactModel(span, first + pair.edge, pair.collider_id, face, pair.factor,
                        float(gap), np.asarray(pair.normal), triangle, pair.contained)


def _query_contacts(request, snapshot, spans, points, pins):
    world = cached_native_collision_world_batch(request.colliders)
    radius = request.collision_policy.collision_radius; slack = request.tolerances.clearance_slack
    threshold = radius + max(4.0 * slack, .25 * radius); owner_span = _owner_span(request, points, pins)
    rows = []
    for span, model in enumerate(spans):
        block = points[model.first:model.last + 1]; edges = _edge_rows(len(block))
        batch = world.contact_pairs(block, edges, _edge_owners(len(block), model.owners), owner_span, threshold)
        rows.extend(_contact_model(span, model.first, pair, snapshot, radius) for pair in batch.pairs)
    return tuple(rows)


def _same_contact(first, second, tolerance):
    if (first.edge, first.collider) != (second.edge, second.collider): return False
    if abs(first.factor - second.factor) > 1.0e-5: return False
    if abs(first.gap - second.gap) > tolerance: return False
    return bool(np.dot(first.normal, second.normal) > 1.0 - 1.0e-5)


def _distinct_contacts(rows, tolerance):
    output = []
    for row in sorted(rows, key=lambda value: (value.edge, value.collider, value.face)):
        if not any(_same_contact(row, prior, tolerance) for prior in output): output.append(row)
    return tuple(output)


def _active_contacts(request, rows):
    radius = request.collision_policy.collision_radius; slack = request.tolerances.clearance_slack
    tolerance = max(8.0 * slack, 1.0e-4 * radius, request.tolerances.numeric_floor)
    distinct = _distinct_contacts(rows, tolerance)
    return tuple(row for row in distinct if row.gap <= tolerance), tolerance, len(distinct)


def _local_points(points, contact):
    return np.asarray(points[contact.edge:contact.edge + 2], dtype=np.float64).reshape(-1)


def _contact_gap(contact, values, radius):
    if contact.contained: return float("nan")
    segment = np.asarray(values, dtype=np.float64).reshape((1, 2, 3))
    return float(segment_triangle_distances(segment, contact.triangle[None, :, :])[0] - radius)


def _analytic_contact_gradient(contact):
    normal = np.asarray(contact.normal)
    return np.r_[(1.0 - contact.factor) * normal, contact.factor * normal]


def _fd_scalar_gradient(function, values, step):
    result = np.empty(len(values))
    for index in range(len(values)):
        plus, minus = values.copy(), values.copy(); plus[index] += step; minus[index] -= step
        result[index] = (function(plus) - function(minus)) / (2.0 * step)
    return result


def _mixed_second(function, values, first, second, step):
    rows = []
    for a, b in ((1., 1.), (1., -1.), (-1., 1.), (-1., -1.)):
        trial = values.copy(); trial[first] += a * step; trial[second] += b * step
        rows.append(function(trial))
    return (rows[0] - rows[1] - rows[2] + rows[3]) / (4.0 * step * step)


def _fd_scalar_hessian(function, values, step):
    count = len(values); output = np.empty((count, count)); center = function(values)
    for first in range(count):
        plus, minus = values.copy(), values.copy(); plus[first] += step; minus[first] -= step
        output[first, first] = (function(plus) - 2.0 * center + function(minus)) / (step * step)
        for second in range(first):
            value = _mixed_second(function, values, first, second, step)
            output[first, second] = output[second, first] = value
    return output


def _contact_derivative(contact, points, radius, steps):
    values = _local_points(points, contact); function = lambda row: _contact_gap(contact, row, radius)
    gradients = tuple(_fd_scalar_gradient(function, values, step) for step in steps)
    analytic = _analytic_contact_gradient(contact)
    hessians = tuple(_fd_scalar_hessian(function, values, step) for step in steps[:2])
    return {"contact": contact, "jacobian": gradients[1], "hessian": hessians[1],
        "jacobian_errors": tuple(_relative_error(analytic, row) for row in gradients),
        "jacobian_stability": _relative_error(gradients[0], gradients[1]),
        "hessian_stability": _relative_error(hessians[0], hessians[1])}


def _constraint_derivatives(active, points, radius, steps):
    if any(row.contained for row in active): return (), "contained active contact has no smooth surface model"
    return tuple(_contact_derivative(row, points, radius, steps) for row in active), ""


def _global_jacobian(models, count):
    output = np.zeros((len(models), 3 * count))
    for index, row in enumerate(models):
        first = 3 * row["contact"].edge; output[index, first:first + 6] = row["jacobian"]
    return output


def _global_constraint_hessians(models, count):
    output = []
    for row in models:
        matrix = np.zeros((3 * count, 3 * count)); first = 3 * row["contact"].edge
        indices = np.arange(first, first + 6); matrix[np.ix_(indices, indices)] = row["hessian"]
        output.append(matrix)
    return tuple(output)


def _nullspace(matrix):
    if not len(matrix): return np.eye(matrix.shape[1]), 0, ()
    _left, values, right = np.linalg.svd(matrix, full_matrices=True)
    tolerance = max(matrix.shape) * np.finfo(float).eps * max(values[0], 1.0)
    rank = int(np.sum(values > tolerance))
    return right[rank:].T, rank, tuple(map(float, values))


def _kkt(gradient, jacobian, gaps, free):
    reduced = jacobian[:, free]; target = gradient[free]
    multipliers = nnls(reduced.T, target, maxiter=max(30, 10 * len(gaps)))[0] if len(gaps) else np.empty(0)
    residual = target - reduced.T @ multipliers
    scale = max(1.0, float(np.linalg.norm(target)))
    complementarity = np.abs(multipliers * gaps) if len(gaps) else np.empty(0)
    threshold = max(1.0e-10, 1.0e-6 * max(multipliers, default=0.0))
    strong = multipliers > threshold
    return reduced, multipliers, strong, residual, {"relative_stationarity": float(np.linalg.norm(residual) / scale),
        "infinity_stationarity": float(np.linalg.norm(residual, np.inf)),
        "maximum_complementarity": float(max(complementarity, default=0.0)),
        "multipliers": tuple(map(float, multipliers)), "strong_contacts": int(np.sum(strong))}


def _lagrangian_hessian(objective, constraints, multipliers):
    output = objective.copy()
    for value, matrix in zip(multipliers, constraints): output -= value * matrix
    return .5 * (output + output.T)


def _spectrum(hessian, jacobian, strong, free):
    selected = jacobian[strong][:, free]; basis, rank, singular = _nullspace(selected)
    reduced = basis.T @ hessian[np.ix_(free, free)] @ basis
    values, vectors = np.linalg.eigh(.5 * (reduced + reduced.T))
    scale = max(1.0, float(np.max(np.abs(values)))) if len(values) else 1.0
    tolerance = 1.0e-6 * scale
    return basis, values, vectors, {"strong_rank": rank, "strong_singular_values": singular,
        "dimension": len(values), "minimum_eigenvalue": float(min(values, default=0.0)),
        "maximum_eigenvalue": float(max(values, default=0.0)), "curvature_tolerance": tolerance,
        "near_zero_count": int(np.sum(np.abs(values) <= tolerance)),
        "lowest_eigenvalues": tuple(map(float, values[:12]))}


def _owner_contacts(request, count):
    _direct, pins = _direct_reference(request); rows = []
    for index, anchor in zip(pins, request.anchors):
        intervals = tuple(row for row in ((index - 1, 0., 1.) if index else None,
            (index, 0., 1.) if index + 1 < count else None) if row is not None)
        if anchor.owner_id: rows.append(V2OwnerContact(anchor.owner_id, (index,), intervals))
    return tuple(rows)


def _normalized_direction(values, count):
    rows = np.asarray(values).reshape((count, 3)); scale = np.max(np.linalg.norm(rows, axis=1))
    return values / max(float(scale), np.finfo(float).eps)


def _retracted_candidate(points, free, direction, jacobian, hessians, step):
    curvature = np.asarray([direction @ matrix[np.ix_(free, free)] @ direction for matrix in hessians])
    correction = np.linalg.lstsq(jacobian[:, free], -curvature, rcond=1.0e-10)[0] if len(jacobian) else np.zeros(len(free))
    flat = points.reshape(-1).copy(); flat[free] += step * direction + .5 * step * step * correction
    return flat.reshape((-1, 3))


def _probe_candidate(request, snapshot, contacts, source, candidate):
    radius = request.collision_policy.collision_radius; slack = request.tolerances.clearance_slack
    static = validate_static_clearance(candidate, snapshot, radius, contacts, slack=slack)
    if not static.valid: return False, False
    sweep = collision_free_step(source, candidate, snapshot, radius, contacts, slack=slack, assume_initial_valid=True)
    return True, bool(sweep.valid and sweep.safe_step >= 1.0 - 1.0e-6)


def _probes(request, snapshot, spans, points, free, basis, values, vectors, jacobian, hessians, scale):
    contacts = _owner_contacts(request, len(points)); initial = _energy(spans, points); rows = []
    for mode in range(min(6, len(values))):
        direction = _normalized_direction(basis @ vectors[:, mode], len(free) // 3)
        for sign in (-1.0, 1.0):
            for fraction in (1.0e-4, 3.0e-4, 1.0e-3, 3.0e-3):
                step = sign * fraction * scale
                candidate = _retracted_candidate(points, free, direction, jacobian, hessians, step)
                valid, swept = _probe_candidate(request, snapshot, contacts, points, candidate)
                delta = _energy(spans, candidate) - initial if valid else None
                rows.append((mode, sign, abs(step), valid, swept, delta))
    return tuple(rows)


def _descent_probe(request, snapshot, spans, points, free, residual, hessian, jacobian, constraints, scale):
    if not np.any(residual): return _zero_descent()
    direction = _normalized_direction(-residual, len(free) // 3)
    gradient = _gradient(spans, points)[free]; curvature = float(direction @ hessian[np.ix_(free, free)] @ direction)
    derivative = float(gradient @ direction); optimal = max(0.0, -derivative / max(curvature, 1.0e-20))
    rows = _descent_rows(request, snapshot, spans, points, free, direction, jacobian,
                         constraints, optimal, scale)
    return _descent_summary(request, spans, points, derivative, curvature, optimal, rows)


def _descent_rows(request, snapshot, spans, points, free, direction, jacobian, constraints, optimal, scale):
    contacts = _owner_contacts(request, len(points)); rows = []; initial = _energy(spans, points)
    for step in sorted({.25 * optimal, .5 * optimal, optimal, 2.0 * optimal, 1.0e-4 * scale}):
        candidate = _retracted_candidate(points, free, direction, jacobian, constraints, step)
        valid, swept = _probe_candidate(request, snapshot, contacts, points, candidate)
        delta = _energy(spans, candidate) - initial if valid else None
        rows.append((step, valid, swept, delta))
    return tuple(rows)


def _descent_summary(request, spans, points, derivative, curvature, optimal, rows):
    initial = _energy(spans, points)
    best = min((row[3] for row in rows if row[1] and row[2]), default=0.0)
    tolerance = max(request.tolerances.clearance_slack, request.tolerances.numeric_floor)
    negligible = optimal <= tolerance and -best / max(1.0, initial) <= 1.0e-9
    return {"directional_derivative": derivative, "curvature": curvature,
        "optimal_step": optimal, "absolute_tolerance": tolerance, "best_energy_delta": best,
        "relative_improvement": -best / max(1.0, initial), "numerically_negligible": negligible,
        "rows": rows}


def _zero_descent():
    return {"directional_derivative": 0.0, "curvature": 0.0, "optimal_step": 0.0,
        "absolute_tolerance": 0.0, "best_energy_delta": 0.0, "relative_improvement": 0.0,
        "numerically_negligible": True, "rows": ()}


def _contact_payload(models):
    return tuple({"span": row["contact"].span, "edge": row["contact"].edge,
        "collider": row["contact"].collider, "face": row["contact"].face,
        "factor": row["contact"].factor, "gap": row["contact"].gap,
        "jacobian_errors": row["jacobian_errors"], "jacobian_stability": row["jacobian_stability"],
        "hessian_stability": row["hessian_stability"]} for row in models)


def _classification(package, objective, contacts, kkt, spectrum, probe_rows, descent, issue):
    if not package.result.validated: return "INVALID_FINAL_RESULT"
    if objective["best_relative_error"] > 1.0e-5: return "OBJECTIVE_DERIVATIVE_ERROR"
    if issue or any(min(row["jacobian_errors"]) > 1.0e-3 for row in contacts): return "CONTACT_MODEL_ERROR"
    if any(row["hessian_stability"] > .2 for row in contacts): return "INCONCLUSIVE_NONSMOOTH_CONTACT"
    confirmed = any(row[1] and row[2] and row[3] is not None and row[3] < -1.0e-9 for row in descent["rows"])
    if confirmed and not descent["numerically_negligible"]: return "NOT_STATIONARY_DESCENT_CONFIRMED"
    minimum, tolerance = spectrum["minimum_eigenvalue"], spectrum["curvature_tolerance"]
    if minimum < -tolerance: return "SADDLE_OR_FEASIBLE_NEGATIVE_CURVATURE"
    if abs(minimum) <= tolerance: return "PLATEAU_OR_DEGENERATE_MINIMUM"
    feasible = [row for row in probe_rows if row[3] and row[4] and row[5] is not None]
    if any(row[5] < -1.0e-9 for row in feasible if row[2] <= 1.0e-3): return "NUMERICAL_LOCAL_DESCENT_FOUND"
    if kkt["relative_stationarity"] > 1.0e-5:
        return "NUMERICALLY_CONVERGED_NEAR_STRICT_LOCAL_MINIMUM"
    return "STRICT_LOCAL_MINIMUM_OF_IMPLEMENTED_OBJECTIVE"


def _analyze(request, snapshot, package):
    points = np.asarray(package.result.points, dtype=np.float64); spans, pins = _span_models(request, points)
    free = _free_dofs(len(points), pins); edge = float(np.median(np.linalg.norm(np.diff(points, axis=0), axis=1)))
    scale = max(request.collision_policy.collision_radius, edge, 1.0e-8); steps = tuple(scale * value for value in (1e-4, 3e-5, 1e-5))
    objective = _objective_check(spans, points, free, steps); queried = _query_contacts(request, snapshot, spans, points, pins)
    active, tolerance, distinct = _active_contacts(request, queried)
    models, issue = _constraint_derivatives(active, points, request.collision_policy.collision_radius, steps)
    jacobian = _global_jacobian(models, len(points)); constraints = _global_constraint_hessians(models, len(points))
    reduced, multipliers, strong, residual, kkt = _kkt(_gradient(spans, points), jacobian, np.asarray([row.gap for row in active]), free)
    lagrangian = _lagrangian_hessian(_objective_hessian(spans, len(points)), constraints, multipliers)
    basis, values, vectors, spectrum = _spectrum(lagrangian, jacobian, strong, free)
    probes = _probes(request, snapshot, spans, points, free, basis, values, vectors, jacobian, constraints, scale)
    descent = _descent_probe(request, snapshot, spans, points, free, residual, lagrangian,
                             jacobian, constraints, scale)
    return _analysis_payload(package, points, pins, objective, queried, distinct, active, tolerance,
        models, issue, kkt, spectrum, probes, descent, request, scale)


def _analysis_payload(package, points, pins, objective, queried, distinct, active, tolerance,
                      models, issue, kkt, spectrum, probes, descent, request, scale):
    classification = _classification(package, objective, models, kkt, spectrum, probes, descent, issue)
    feasible = tuple(row for row in probes if row[3] and row[4])
    return {"classification": classification, "termination": package.result.termination.value,
        "validated": package.result.validated, "node_count": len(points), "pin_indices": pins,
        "solver_diagnostics": vars(package.result.diagnostics), "objective_derivative": objective,
        "contacts": {"queried": len(queried), "distinct": distinct, "active": len(active),
            "active_tolerance": tolerance, "issue": issue, "derivatives": _contact_payload(models)},
        "kkt": kkt, "spectrum": spectrum,
        "scales": {"collision_radius": request.collision_policy.collision_radius,
            "clearance_slack": request.tolerances.clearance_slack, "local_edge_scale": scale},
        "projected_descent": descent,
        "probes": {"tested": len(probes), "fully_feasible": len(feasible),
            "best_energy_delta": min((row[5] for row in feasible if row[5] is not None), default=None),
            "rows": probes}}


def _capture(args):
    root = common._root(); fiber = common._fiber(root, args.fiber_id)
    request, snapshot, capture = p3._capture(root, fiber, bpy.context.evaluated_depsgraph_get())
    return fiber, p3._override_cap(request, args.accepted_cap), snapshot, capture


def main():
    args = _args(); fiber, request, snapshot, capture = _capture(args); started = perf_counter()
    package = solve_subfiber_sqp_fixed(request, snapshot=snapshot)
    record = {"file": bpy.data.filepath, "file_sha256": common._file_hash(bpy.data.filepath),
        "fiber": fiber.id, "capture_ms": capture, "solve_ms": 1000.0 * (perf_counter() - started),
        "analysis": _analyze(request, snapshot, package)}
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("AF_V2_SQP_OPTIMALITY", json.dumps({"classification": record["analysis"]["classification"],
        "kkt": record["analysis"]["kkt"], "spectrum": record["analysis"]["spectrum"],
        "contacts": record["analysis"]["contacts"]}, default=str), flush=True)


if __name__ == "__main__":
    main()
