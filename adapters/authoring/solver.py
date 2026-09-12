"""Adapter to the existing independently validated native V3 solver."""
from time import perf_counter
import numpy as np
from ...core.authoring.compilation import material_coordinates
from ...core.authoring.errors import require
from ...core.authoring.errors import AuthoringError
from ...core.authoring.geometry import world_vertices
from ...core.vcp.v2.contracts import (V2Anchor, V2Settings, V2Request, V2CollisionPolicy,
                                    V2ResolvedTolerances, V2ArrayColliderSnapshot)
from ...core.vcp.v3.production import begin_v3
from ...core.vcp.v2.scales import resolve_tolerances
from ...core.vcp.v2.collision import cached_native_collision_world_batch
from ...core.vcp.fiber_anchor_preflight import evaluate_anchor_preflight


class NativeFiberSolver:
    def solve(self, plan, snapshot, budget_ms):
        request = request_for(plan, snapshot)
        preflight(request, plan)
        session = begin_v3(request)
        deadline = perf_counter() + budget_ms / 1000
        try:
            while not session.done:
                if perf_counter() >= deadline:
                    raise failure(plan, "SOLVER_BUDGET", "Time budget exhausted", session.seed)
                session.step()
            return finished(request, plan, session.package.result)
        finally:
            if not session.done:
                session.cancel()


def finished(request, plan, result):
    if not result.validated:
        raise failure(plan, "FIBER_UNSAFE", result.message, result.points)
    points = np.asarray(result.points)
    samples = material_coordinates(points, plan)
    validate_final(request, plan, points, samples)
    return points, samples, result.termination.value.lower()


def failure(plan, code, message, points):
    error = AuthoringError(code, plan.id + ": " + message, "/muscles/" + plan.id.split(".u")[0], (plan.id,))
    error.preview = dict(kind="unpublished_route", fiber=plan.id, points=np.asarray(points).tolist() if points is not None else [],
                         anchors=[dict(owner=a.owner, point=list(a.point), normal=list(a.normal)) for a in plan.anchors])
    return error


def preflight(request, plan):
    result = evaluate_anchor_preflight(request.anchors, request.colliders, {}, request.collision_policy.collision_radius,
                                      request.tolerances.clearance_slack, world=cached_native_collision_world_batch(request.colliders))
    if not result.valid:
        row = result.violations[0]
        message = f"Anchor {row.authored_index} on {row.owner_id} blocked by {row.blocker_id}. {row.action}"
        raise failure(plan, "ANCHOR_BLOCKED", message, [a.point for a in plan.anchors])


def request_for(plan, snapshot):
    settings = V2Settings(topology="CYCLIC" if plan.closed else "OPEN", quality="FINAL",
                          node_count=plan.count, max_accepted_steps=180)
    roles = ["LOOP"] * len(plan.anchors) if plan.closed else ["ENDPOINT_A"] + ["TOUCH"] * (len(plan.anchors)-2) + ["ENDPOINT_B"]
    anchors = tuple(V2Anchor(a.point, a.owner, role, i) for i,(a,role) in enumerate(zip(plan.anchors, roles)))
    colliders = tuple(V2ArrayColliderSnapshot(m.id, m.id, world_vertices(m), m.triangles) for m in snapshot.meshes)
    policy = V2CollisionPolicy(collision_radius=plan.collision_radius)
    tolerances = resolve_tolerances(colliders, policy.collision_radius, settings.quality)
    return V2Request(1, snapshot.id, snapshot.id, snapshot.revision, settings, tolerances, policy, anchors, colliders)


def validate_final(request, plan, points, samples):
    indices = [int(np.argmin(abs(samples-s))) for s in plan.stations]
    owners = {index: a.owner for index,a in zip(indices, plan.anchors)}
    edges = [(i, (i+1) % len(points)) for i in range(len(points) if plan.closed else len(points)-1)]
    edge_owners = [(owners.get(a, ""), owners.get(b, "")) for a,b in edges]
    radius = request.collision_policy.collision_radius
    span = max(2.5 * radius, max(np.linalg.norm(points[b]-points[a]) for a,b in edges))
    world = cached_native_collision_world_batch(request.colliders)
    result = world.validate(points, tuple(edges), tuple(edge_owners), span, max(0, radius-request.tolerances.clearance_slack))
    require(all(result.clear), "RESAMPLING_COLLISION", plan.id)
