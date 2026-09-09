"""Read-only authoring operations."""
from ...core.authoring import reports
from ...core.authoring.regions import RegionResolver
from ...core.authoring.errors import require, AuthoringError
from ...core.authoring.inspection import svg

FEATURES = ["regions.projected_charts.v1","fibers.named_stations.v1","muscles.material_boundary.v1",
            "muscles.closed_loft.v1","contacts.default_inflated.v1","contacts.open_loft_refinement.v1",
            "regions.landmark_box.v1","regions.local_projection_charts.v1","surfaces.station_conformance.v1",
            "shape.material_sections.v1","authoring.drafts.v1","contacts.material_repair.v1"]


def describe(service,request,snapshot):
    result = reports.response(request,snapshot.revision)
    result["capabilities"] = dict(operations=["describe","resolve","build","inspect","patch","resume","job_status","export",
                                            *(["draft","patch_draft","publish_draft"] if request["version"] == "0.3.0" else [])],
                                features=FEATURES,backend_version="authoring-0.3.0",max_fibers_per_muscle=128,max_nodes_per_fiber=512)
    if request["params"]["scope"] == "scene":
        result["entities"] = [reports.entity(m.id,"target",definition=dict(concept=m.concept or m.id,side=m.side,
                               binding=dict(kind="scene_scp_id",id=m.id))) for m in snapshot.meshes]
        result["assets"].append(service.store.asset(scene_geometry(snapshot)))
    else:
        result["entities"] = inventory(service,request,snapshot)
    return result


def inventory(service,request,snapshot):
    if request["params"]["scope"] == "capabilities":
        return []
    documents = service.scene.documents()
    group = "recipes" if request["params"]["scope"] == "recipes" else "regions"
    wanted = request["params"].get("ids",())
    return [reports.entity(key,"recipe" if group == "recipes" else "region",definition=value)
            for doc in documents for key,value in doc[group].items() if not wanted or key in wanted]


def scene_geometry(snapshot):
    return dict(scene_id=snapshot.id, reference_pose=snapshot.pose, revision=snapshot.revision,
                meshes=[dict(id=m.id, owner_local_vertices=m.vertices.tolist(), triangles=m.triangles.tolist(),
                             matrix_world=m.matrix.tolist(), concept=m.concept, side=m.side, native_name=m.label,
                             bounds=[m.vertices.min(0).tolist(),m.vertices.max(0).tolist()]) for m in snapshot.meshes])


def resolve(service,request,snapshot):
    require(request["params"]["expected_scene_revision"] == snapshot.revision,"STALE_REVISION")
    document = request["params"]["document"]
    require(document["context"]["reference_pose"] == snapshot.pose,"REFERENCE_POSE_MISMATCH")
    resolver = RegionResolver(document,snapshot)
    result = reports.response(request,snapshot.revision)
    for name in document["regions"]:
        resolve_one(service, resolver, result, name)
    return result


def resolve_one(service, resolver, result, name):
    try:
        samples = resolver.resolve(name)
        result["assets"].append(service.store.asset(dict(region=name,samples=samples)))
        result["entities"].append(reports.entity(name,"region",checks={"mapping":"pass"}))
    except AuthoringError as error:
        result["status"] = "unresolved"
        result["diagnostics"].append(error.diagnostic())
        result["entities"].append(reports.entity(name,"region","unresolved",checks={"mapping":"fail"}))


def stored(service,request,snapshot):
    key = [snapshot.id,request["params"]["document_id"]]
    value = (service.store.get("drafts",key) if request["params"].get("source") == "draft" else previous_document(service, *key))
    require(value is not None,"DOCUMENT_NOT_FOUND")
    return value


def previous_document(service, scene_id, document_id):
    if hasattr(service.scene, "document"):
        return service.scene.document(document_id)
    return service.store.get("documents", [scene_id, document_id])


def inspect(service,request,snapshot):
    value = stored(service,request,snapshot)
    result = reports.response(request,snapshot.revision)
    require(value["scene_revision"] == snapshot.revision,"STALE_OUTPUT")
    for identity in request["params"]["ids"]:
        output = value["results"].get(identity)
        require(output is not None,"ENTITY_NOT_FOUND",identity)
        result["assets"].append(service.store.asset(output,"report"))
        for view in request["params"]["views"]:
            result["assets"].append(service.store.image(svg(snapshot, output, view)))
        result["entities"].append(reports.entity(identity,"muscle",state="unchanged"))
    return result


def export(service,request,snapshot):
    value = stored(service,request,snapshot)
    result = reports.response(request,snapshot.revision)
    result["assets"].append(service.store.asset(value["document"],"authoring"))
    if request["params"]["include"] == "authoring_and_bindings":
        result["assets"].append(service.store.asset(binding_export(value),"bindings"))
    return result


def binding_export(value):
    return dict(native_ids=value.get("native_ids",{}), scene_revision=value["scene_revision"],
                resolved_anchors={name: {f["id"]: f["anchors"] for f in output.get("fibers",[])}
                                  for name,output in value["results"].items()})


def job_status(service,request,snapshot):
    value = service.store.get("jobs",[snapshot.id,request["params"]["job_id"]])
    require(value is not None,"JOB_NOT_FOUND")
    result = reports.response(request,snapshot.revision)
    result["job"] = value["job"]
    return result
