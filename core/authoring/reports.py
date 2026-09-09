"""Wire responses independent of Blender UI summaries."""
DIMENSIONS = ("mapping", "anchors", "route", "surface", "shape", "inflated_contact", "native_editability", "persistence")


def response(request, revision="unavailable"):
    return dict(dsl="anthroforge.authoring.protocol",version=request.get("version","0.2.0"),message_type="response",
                request_id=request.get("request_id","invalid_request"),op=request.get("op","describe"),
                status="success",scene_id=request.get("params",{}).get("scene_id","unavailable"),
                scene_revision=revision,published=False,entities=[],diagnostics=[],assets=[],cost={})


def entity(identity, kind, state="resolved", checks=None, **extra):
    validation = dict.fromkeys(DIMENSIONS,"not_evaluated")
    validation.update(checks or {})
    return dict(id=identity,kind=kind,state=state,validation=validation,**extra)


def native_ids(value):
    return dict(muscle=[value["muscle"]], surface=[value["surface"]], fibers=list(value["fibers"].values()))
