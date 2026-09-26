"""One muscle build, default volume checks and selective refinement."""
import numpy as np
from time import perf_counter
from . import compilation, inflation, contact, surface_checks, native_geometry, shape, contact_repair, repair_comparison
from .errors import require, AuthoringError


def evaluate_muscle(document, name, resolver, solver, checkpoint=None, plan_transform=None):
    policy = evaluation_policy(document, name, resolver)
    plans = compilation.fibers(document, name, resolver)
    plans = plan_transform(plans) if plan_transform else plans
    baseline = solve_rows(plans, resolver.snapshot, policy, solver, resolver.deadline)
    refs = references(baseline[0], plans[0].closed)
    result = evaluated(document, name, resolver, plans, baseline, refs)
    if checkpoint:
        checkpoint(name, result)
    if result["contact"]["area"] and policy["refinement"]["method"] != "none":
        require(plan_transform is None, 'ROUTE_OVERRIDE_REFINEMENT_UNSUPPORTED')
        result = refine(document, name, resolver, solver, result, refs)
    if result["contact"]["area"]:
        raise penetration_error(name, result)
    return completed(result,resolver)


def evaluation_policy(document, name, resolver):
    policy = document['policies'][document['muscles'][name]['policy']]
    resolver.deadline = perf_counter()+policy['total_budget_ms']/1000 if 'total_budget_ms' in policy else None
    return policy


def completed(result,resolver):
    resolver.check_budget()
    return result


def penetration_error(name, result):
    error = AuthoringError("INFLATED_PENETRATION", name, "/muscles/"+name)
    error.preview = result
    return error


def solve_rows(plans, snapshot, policy, solver, deadline=None):
    outputs = []
    for plan in plans:
        remaining = (deadline-perf_counter())*1000 if deadline is not None else policy["solver_budget_ms"]
        require(remaining > 0,"TOTAL_BUDGET_EXHAUSTED")
        outputs.append(solver.solve(plan,snapshot,min(policy["solver_budget_ms"],remaining)))
    return [item[0] for item in outputs], [item[1] for item in outputs], [item[2] for item in outputs]


def references(rows, closed):
    lengths = [np.linalg.norm(np.diff(np.vstack((row,row[0])) if closed else row,axis=0),axis=1).sum() for row in rows]
    ends = [reference_samples(row,closed) for row in (rows[0],rows[-1])]
    width = np.linalg.norm(ends[1]-ends[0],axis=1)
    return dict(reference_fiber_length=float(np.mean(lengths)),reference_attachment_width=float(np.mean(width)))


def reference_samples(row,closed):
    if not closed:
        return np.asarray(row)[[0,-1]]
    points = np.vstack((row,row[0]))
    arc = np.r_[0.,np.cumsum(np.linalg.norm(np.diff(points,axis=0),axis=1))]
    require(arc[-1] > 1e-12,"DEGENERATE_FIBER_SPAN")
    return np.column_stack([np.interp(np.linspace(0,arc[-1],65),arc,points[:,axis]) for axis in range(3)])


def evaluated(document, name, resolver, plans, solved, refs):
    rows, row_s, terminations = solved
    s = np.linspace(0., 1., plans[0].count, endpoint=not plans[0].closed)
    muscle = document["muscles"][name]
    preset = document["volume_presets"][muscle["volume_preset"]]
    config = inflation.resolved_preset(preset, resolver, refs)
    base,u = build_grid(document,name,resolver,plans,rows,row_s,s)
    native, props, point = native_geometry.evaluate(base,u,s,config,plans[0].closed)
    result = pack_result(plans,rows,s,terminations,native.base_vertices,native.inflated_vertices,u,native.faces,config,{},refs,row_s)
    result.update(native_properties=props, native_control_world=point)
    _envelope_output(result, config, base)
    return checked_result(result, document, name, resolver)


def checked_result(result, document, name, resolver):
    base = np.array(result["base"]).reshape(len(result["u"]),len(result["s"]),3)
    inflated = np.array(result.get("side_a", result["inflated"])).reshape(base.shape)
    closed, config, refs = result["fibers"][0]["closed"], result["config"], result["references"]
    try:
        _check_sides(result, base, inflated, closed)
        result["shape"] = shape.measurements(base,inflated,result["u"],result["s"],config,closed,resolver,refs)
        shape.validate(result["shape"])
        tolerance = resolver.measure(document["policies"][document["muscles"][name]["policy"]]["penetration_tolerance"],refs)
        result["contact"] = evaluate_contact(resolver, np.asarray(result["inflated"]), result.get("inflated_faces", result["faces"]), tolerance)
        contact_repair.annotate(result)
    except AuthoringError as error:
        error.preview, error.pointer = result, "/muscles/"+name
        raise
    return result


def evaluate_contact(resolver,inflated,faces,tolerance):
    resolver.check_budget()
    args = (inflated.reshape(-1,3),np.asarray(faces),resolver.snapshot,tolerance)
    if resolver.deadline is not None:
        require(hasattr(resolver.contacts,"evaluate_bounded"),"UNSUPPORTED_CONTACT_BUDGET")
        return resolver.contacts.evaluate_bounded(*args,resolver.check_budget)
    return resolver.contacts.evaluate(*args)


def build_grid(document,name,resolver,plans,rows,row_s,s):
    base,u = native_geometry.loft(rows,[p.u for p in plans],plans[0].closed)
    policy = document["policies"][document["muscles"][name]["policy"]]
    require(base.shape[0]*base.shape[1] <= policy.get("max_surface_vertices",1000000), "SURFACE_VERTEX_BUDGET")
    return base,u


def pack_result(plans,rows,s,terminations,base,inflated,u,faces,config,report,refs,row_s):
    fibers = [dict(id=p.id,u=p.u,closed=p.closed,stations=list(p.stations),points=np.asarray(row).tolist(),
                   anchors=[anchor_record(a) for a in p.anchors]) for p,row in zip(plans,rows)]
    for fiber, coordinates in zip(fibers, row_s):
        fiber["material_s"] = list(coordinates)
    return dict(fibers=fibers,s=list(s),u=list(u),base=base.reshape(-1,3).tolist(),inflated=inflated.reshape(-1,3).tolist(),
                faces=faces.tolist(),config=config,contact=report,references=refs,terminations=terminations)


def anchor_record(anchor):
    result = dict(owner=anchor.owner,point=list(anchor.point),surface=list(anchor.surface),normal=list(anchor.normal),offset=anchor.offset)
    if anchor.surface_binding is not None:
        indices, weights = anchor.surface_binding
        result['surface_binding'] = dict(tri_vidx=list(indices),tri_weights=list(weights))
    return result


def check_shape(base, inflated, u, s, config, closed, resolver, refs):
    normal = inflation.normals(base,closed) * (-1 if config["flip_normals"] else 1)
    heights = np.einsum("ijk,ijk->ij",inflated-base,normal)
    for check in config["shape_checks"]:
        samples = np.linspace(*check["u_range"],65)
        fields = np.repeat(heights[...,None],3,axis=2)
        values = [inflation.sample(fields,u,s,x,check["s"],closed)[0] for x in samples]
        value = max(values) if check["statistic"] == "max" else float(np.mean(values))
        low,high = [resolver.measure(check[key],refs) for key in ("minimum","maximum")]
        require(low <= value <= high, "VOLUME_OUT_OF_RANGE", f"Measured {value:g}; expected {low:g}..{high:g}")


def refine(document,name,resolver,solver,result,refs):
    options,tolerance,baseline_count,rejected = refinement_setup(document,name,resolver,result,refs)
    for _ in range(options["max_attempts"]):
        if not result["contact"]["area"] or len(result["fibers"])-baseline_count >= options["max_added_fibers"]:
            break
        candidate = contact_repair.candidate(result,rejected) if document["version"] == "0.3.0" else candidate_u(result, rejected)
        if candidate is None:
            break
        updated = try_candidate(document,name,resolver,solver,result,candidate,refs)
        result,accepted = consider_candidate(result,updated,candidate,options,tolerance,resolver,document["version"])
        if not accepted:
            rejected.add(candidate)
    return result


def consider_candidate(result,updated,candidate,options,tolerance,resolver,version):
    try:
        accepted = repair_comparison.acceptable(result,updated,options,tolerance,resolver,version)
    except AuthoringError as error:
        error.preview = result
        raise
    attempts = result.setdefault("repair_attempts",[])
    attempts.append(dict(u=candidate,accepted=accepted,reason="accepted" if accepted else
                         "route_or_surface_validation" if updated is None else "contact_improvement_insufficient"))
    if accepted:
        updated["repair_attempts"] = attempts
        return updated,True
    return result,False


def refinement_setup(document,name,resolver,result,refs):
    policy = document["policies"][document["muscles"][name]["policy"]]
    return policy["refinement"], resolver.measure(policy["penetration_tolerance"],refs), len(result["fibers"]), set()


def candidate_u(result, rejected=()):
    columns = len(result["s"])
    face_count = len(result["faces"])
    values = [row["u"] for row in result["fibers"]]
    scores = dict.fromkeys(((a+b)/2 for a,b in zip(values,values[1:])), 0.)
    vertices = np.array(result["inflated"])
    for index in result["contact"]["triangles"]:
        face = result["faces"][index % face_count]
        position = np.mean([result["u"][v//columns] for v in face])
        pair = next(((a,b) for a,b in zip(values,values[1:]) if a <= position <= b), (values[0],values[-1]))
        scores[sum(pair)/2] += float(np.linalg.norm(np.cross(vertices[face[1]]-vertices[face[0]],vertices[face[2]]-vertices[face[0]])))
    return max((key for key in scores if key not in rejected), key=scores.get, default=None)


def try_candidate(document,name,resolver,solver,result,candidate,refs):
    extra = [row["u"] for row in result["fibers"]] + [candidate]
    plans = compilation.fibers(document,name,resolver,extra)
    policy = document["policies"][document["muscles"][name]["policy"]]
    try:
        solved = solve_rows(plans,resolver.snapshot,policy,solver,resolver.deadline)
        return evaluated(document,name,resolver,plans,solved,refs)
    except AuthoringError as error:
        if "BUDGET" in error.code:
            error.preview = result
            raise
        return None


def _envelope_output(output, config, base):
    if 'envelope' not in config: return
    from .envelope_numeric import evaluate_output
    from .native_geometry import numeric_properties
    from ..vcp.muscle_numeric import MuscleNumericSpec, make_muscle_request
    spec = MuscleNumericSpec(target_count=base.shape[1], densify=False, closed_u=False, close_across_fibers=False,
        topology_flip_normals=False, closed_v=False, control_world=tuple(output['native_control_world']), **numeric_properties(output['native_properties']))
    evaluate_output(output, config['envelope'], make_muscle_request('authored', base, spec))
    output['measurement_scope'] = 'side_a_shape_checks; both_sides_contact; envelope_surface_diagnostics'


def _check_sides(result, base, inflated, closed):
    surface_checks.check(base, inflated, closed)
    if 'side_b' in result: surface_checks.check(base, np.asarray(result['side_b']).reshape(base.shape), closed)
