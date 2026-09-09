"""Write use cases own orchestration; the scene adapter owns mutations."""
from ...core.authoring.codec import decode, digest
from ...core.authoring.errors import require
from ...core.authoring.validation import document as validate_document
from ...core.authoring.patching import apply_patch
from ...core.authoring.regions import RegionResolver
from ...core.authoring.evaluation import evaluate_muscle
from ...core.authoring import reports
from .native_queries import stored, previous_document
from .incremental import reusable


def build(service,request,snapshot):
    params = request["params"]
    require(params["expected_scene_revision"] == snapshot.revision,"STALE_REVISION")
    document = decode(params["document"])
    previous = previous_document(service,snapshot.id,document["document_id"])
    require(document["revision"] == (previous["document"]["revision"] if previous else 0),"STALE_DOCUMENT_REVISION")
    require(document["context"]["reference_pose"] == snapshot.pose,"REFERENCE_POSE_MISMATCH")
    resolver = RegionResolver(document,snapshot,service.contacts)
    for name in document["regions"]:
        resolver.resolve(name)
    job = begin_job(service,request,snapshot,document)
    job["results"].update(reusable(document,previous,snapshot))
    outputs = run_muscles(service,document,resolver,job)
    return publish(service,request,snapshot,document,outputs,previous,job)


def begin_job(service,request,snapshot,document):
    job_id = "job_" + digest([snapshot.id,request["request_id"]])[:24]
    job = dict(id=job_id,state="running",document_revision=document["revision"],recipe_digest=digest(document),
               geometry_digest=snapshot.revision,completed_entities=[])
    record = dict(job=job,document=document,results={})
    service.last_job = record
    service.store.put("jobs",[snapshot.id,job_id],record)
    return record


def run_muscles(service,document,resolver,record):
    for name in document["muscles"]:
        if name in record["results"]:
            continue
        record["results"][name] = evaluate_muscle(document,name,resolver,service.solver)
        record["job"]["completed_entities"].append(name)
        record["job"]["state"] = "checkpointed"
        service.store.put("jobs",[resolver.snapshot.id,record["job"]["id"]],record)
    return record["results"]


def publish(service,request,snapshot,document,outputs,previous,record):
    document = decode(document)
    document["revision"] += 1
    with service.scene.publish(snapshot,document,outputs,previous) as ids:
        current = service.scene.capture(snapshot.id)
        result = published_response(service,request,current,document,outputs,ids,record)
        value = dict(document=document,results=outputs,native_ids=ids,scene_revision=current.revision,
                     receipt=dict(request_id=request["request_id"],digest=digest(request),response=result))
        if hasattr(service.scene,"persist"):
            service.scene.persist(value)
        service.store.put("documents",[snapshot.id,document["document_id"]],value)
    record["job"].update(state="completed",document_revision=document["revision"])
    finish_job(service, snapshot, record)
    return result


def published_response(service,request,current,document,outputs,ids,record):
    result = reports.response(request,current.revision)
    result.update(published=True,document_revision=document["revision"],
                  job=dict(record["job"],state="completed",document_revision=document["revision"]))
    result["assets"] = [service.store.asset(output) for output in outputs.values()]
    result["entities"] = [reports.entity(name,"muscle","published",native_ids=reports.native_ids(ids[name]),
        checks=dict(mapping="pass",anchors="pass",route="pass",surface="pass",shape="needs_review",inflated_contact="pass",native_editability="pass")) for name in outputs]
    result["cost"] = dict(fibers_solved=dict(value=getattr(service.solver,"solved",sum(len(r["fibers"]) for r in outputs.values())),unit="count"),
                          fibers_cached=dict(value=getattr(service.solver,"hits",0),unit="count"))
    return result


def patch(service,request,snapshot):
    previous = stored(service,request,snapshot)
    require(previous["document"]["revision"] == request["params"]["expected_document_revision"],"STALE_DOCUMENT_REVISION")
    document = validate_document(apply_patch(previous["document"],request["params"]["operations"]))
    adapted = dict(request,params=dict(scene_id=snapshot.id,expected_scene_revision=request["params"]["expected_scene_revision"],document=document))
    return build(service,adapted,snapshot)


def resume(service,request,snapshot):
    require(request["params"]["expected_scene_revision"] == snapshot.revision,"STALE_REVISION")
    record = service.store.get("jobs",[snapshot.id,request["params"]["job_id"]])
    require(record is not None,"JOB_NOT_FOUND")
    require(record["job"]["state"] != "completed","JOB_ALREADY_COMPLETED")
    require(record["job"]["geometry_digest"] == snapshot.revision,"STALE_CHECKPOINT")
    require(record["document"]["revision"] == request["params"]["expected_document_revision"],"STALE_DOCUMENT_REVISION")
    document = validate_document(record["document"])
    require(record["job"]["recipe_digest"] == digest(document),"CHECKPOINT_DOCUMENT_CHANGED")
    service.last_job = record
    resolver = RegionResolver(document,snapshot,service.contacts)
    run_muscles(service,document,resolver,record)
    previous = previous_document(service,snapshot.id,document["document_id"])
    return publish(service,request,snapshot,document,record["results"],previous,record)


def finish_job(service, snapshot, record):
    import logging
    try:
        service.store.put("jobs", [snapshot.id, record["job"]["id"]], record)
    except OSError:
        logging.getLogger(__name__).exception("Published document; completion journal write failed")
