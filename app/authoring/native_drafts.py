"""Durable, revisioned drafts remain editable even when geometry is unresolved."""
from ...core.authoring.codec import decode
from ...core.authoring.errors import require, AuthoringError
from ...core.authoring.validation import document as validate
from ...core.authoring.patching import apply_patch
from ...core.authoring.regions import RegionResolver
from ...core.authoring.evaluation import evaluate_muscle
from ...core.authoring import reports
from . import commands, native_queries as queries


def draft(service,request,snapshot):
    params = request["params"]
    require(params["expected_scene_revision"] == snapshot.revision,"STALE_REVISION")
    document = decode(params["document"])
    key = [snapshot.id,document["document_id"]]
    previous = service.store.get("drafts",key)
    require(params["expected_draft_revision"] == (previous or {}).get("draft_revision",0),"STALE_DRAFT_REVISION")
    require(document["context"]["reference_pose"] == snapshot.pose,"REFERENCE_POSE_MISMATCH")
    record = dict(document=document,draft_revision=params["expected_draft_revision"]+1,
                  scene_revision=snapshot.revision,results={},state="evaluating")
    service.store.put("drafts",key,record)
    result = evaluate(service,request,snapshot,record)
    record.update(response=result,state=result["status"])
    service.store.put("drafts",key,record)
    return result


def evaluate(service,request,snapshot,record):
    result = reports.response(request,snapshot.revision)
    result["draft_revision"] = record["draft_revision"]
    try:
        evaluate_geometry(service,snapshot,record,result)
    except AuthoringError as error:
        result.update(status="unresolved")
        result["diagnostics"].append(error.diagnostic())
    return result


def evaluate_geometry(service,snapshot,record,result):
    resolver = RegionResolver(record["document"],snapshot,service.contacts)
    for name in record["document"]["regions"]:
        queries.resolve_one(service,resolver,result,name)
    if result["status"] == "success":
        for name in record["document"]["muscles"]:
            evaluate_one(service,resolver,result,record,name)


def evaluate_one(service,resolver,result,record,name):
    try:
        output = evaluate_muscle(record["document"],name,resolver,service.solver)
        record["results"][name] = output
        result["assets"].append(service.store.asset(output,"report"))
        result["entities"].append(reports.entity(name,"muscle",checks=dict(shape="needs_review",inflated_contact="pass")))
    except AuthoringError as error:
        result["status"] = "unresolved"
        result["diagnostics"].append(error.diagnostic())
        if hasattr(error,"preview"):
            record["results"][name] = error.preview
            result["assets"].append(service.store.asset(error.preview))


def load(service,request,snapshot):
    params = request["params"]
    require(params["expected_scene_revision"] == snapshot.revision,"STALE_REVISION")
    record = service.store.get("drafts",[snapshot.id,params["document_id"]])
    require(record is not None,"DRAFT_NOT_FOUND")
    require(record["draft_revision"] == params["expected_draft_revision"],"STALE_DRAFT_REVISION")
    return record


def patch_draft(service,request,snapshot):
    record = load(service,request,snapshot)
    document = validate(apply_patch(record["document"],request["params"]["operations"]))
    params = dict(request["params"],document=document)
    return draft(service,dict(request,params=params),snapshot)


def publish_draft(service,request,snapshot):
    record = load(service,request,snapshot)
    require(record["scene_revision"] == snapshot.revision,"STALE_DRAFT_GEOMETRY")
    require(record["state"] == "success","DRAFT_UNRESOLVED")
    params = dict(scene_id=snapshot.id,expected_scene_revision=snapshot.revision,document=record["document"])
    result = commands.build(service,dict(request,params=params),snapshot)
    result["draft_revision"] = record["draft_revision"]
    return result
