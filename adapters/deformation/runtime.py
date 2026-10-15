"""Main-thread debounce, revision validation and position-only publication."""
import time
import bpy
from . import jobs, request
from ...core.deformation.scheduling import UpdateQueue
from ...core.warnings import session

QUEUE = UpdateQueue()
SEEN, OWNERS, RUNNING, MODES = {}, {}, {}, {}


def enqueue(root, scene, immediate=False):
    key = session.id_token(root); current = request.revision(root)
    OWNERS[key] = scene.name,root.name; SEEN[key] = current
    QUEUE.enqueue(key,current,time.monotonic()-(.3 if immediate else 0))
    root["af_deformation_status"] = "Waiting for anatomy update"


def initialize(root, scene):
    key = session.id_token(root)
    if key in jobs.ACTIVE: raise RuntimeError("Cancel the current update before initializing.")
    MODES[key] = "INITIALIZE_DEFORMATION"
    enqueue(root,scene,True)


def discover():
    for scene in bpy.data.scenes:
        for root in scene.objects:
            if not root.get("anthroforge_root") or root.get("af_deformation_reference") is None: continue
            if root.get("af_deformation_invalid"): continue
            key = session.id_token(root); current = request.revision(root)
            stale = root.get("af_deformation_construction_signature","") != request.construction_signature(root)
            if root.get("af_deformation_construction_stale") != stale: root["af_deformation_construction_stale"] = stale
            if key not in SEEN: SEEN[key] = current
            elif SEEN[key] != current: enqueue(root,scene)


def owners(key):
    names = OWNERS.get(key,("","")); scene = bpy.data.scenes.get(names[0])
    return scene, None if scene is None else scene.objects.get(names[1])


def launch(key):
    scene, root = owners(key)
    if root is None: QUEUE.cancel(key); return
    if constructing(scene,root): return
    options = dict(strategy=root.af_topology_settings.deformation_method,failure_policy="STOP",settings=request.settings(root))
    mode = MODES.pop(key,"DEFORM")
    from .initialization import capture
    prepare = capture if mode == "INITIALIZE_DEFORMATION" else request.prepare
    with bpy.context.temp_override(scene=scene):
        job = jobs.start(key,root,bpy.app.binary_path,lambda spec:prepare(bpy.context,root,spec),options,mode)
    RUNNING[key] = QUEUE.start(key,lambda:jobs.cancel(key),time.monotonic())
    root["af_deformation_status"] = "Preparing deformation"


def constructing(scene, root):
    from ..draft_skin.jobs import active_job as draft_job
    from ..topology.jobs import active_job as topology_job
    from ..warm_update.jobs import active_job as warm_job
    return any(job is not None and job.spec.root_name == root.name
               for job in (draft_job(scene),topology_job(scene),warm_job(scene)))


def complete(key, status):
    from .publication import publish
    from ..warm_update.jobs import result_for_job
    scene, root = owners(key); job = jobs.ACTIVE.pop(key); revision = RUNNING.pop(key)
    current = request.revision(root) if root is not None else None
    accepted = QUEUE.finish(key,revision,current)
    if root is None: return
    if not accepted: root["af_deformation_status"] = "Obsolete result discarded"; return
    if status.state != "SUCCEEDED": raise RuntimeError(status.message or "Deformation failed; previous mesh retained.")
    publish_completed(scene,root,job)


def publish_completed(scene, root, job):
    from .publication import publish
    from ..warm_update.jobs import result_for_job
    if job.spec.mode == "INITIALIZE_DEFORMATION":
        from .initialization import publish as initialize_reference
        initialize_reference(scene,root,job)
        root["af_deformation_invalid"] = False
        root["af_deformation_construction_signature"] = request.construction_signature(root)
        SEEN[session.id_token(root)] = request.revision(root)
        root["af_deformation_status"] = "Reference ready"; return
    _, result, summary = result_for_job(job)
    publish(root,request.topology(root,scene),result,summary["reference_signature"])
    root["af_deformation_issue_count"] = len(result.statistics.get("issues",()))
    root["af_deformation_status"] = "Updated"; root["af_deformation_seconds"] = summary["elapsed_seconds"]


def report_error(key, error):
    from .issues import report
    scene, root = owners(key)
    if root is not None:
        root["af_deformation_status"] = str(error)
        if "material addresses changed" in str(error) or "sample address" in str(error): root["af_deformation_invalid"] = True
        report(scene,root,str(error))
    if key not in jobs.ACTIVE: QUEUE.cancel(key)


def tick():
    discover()
    for key in tuple(jobs.ACTIVE):
        try:
            status = jobs.poll(key); scene, root = owners(key)
            if root is not None: root["af_deformation_status"] = status.stage
            if status.state in {"SUCCEEDED","FAILED","CANCELLED"}: complete(key,status)
        except Exception as error: report_error(key,error)
    for key in QUEUE.ready(time.monotonic()):
        try: launch(key)
        except Exception as error: report_error(key,error)
    return .1


def register():
    if not bpy.app.timers.is_registered(tick): bpy.app.timers.register(tick,persistent=True)
    from .lifecycle import register as register_hooks
    register_hooks()


def shutdown():
    QUEUE.reset(); jobs.shutdown(); SEEN.clear(); OWNERS.clear(); RUNNING.clear(); MODES.clear()
    if bpy.app.timers.is_registered(tick): bpy.app.timers.unregister(tick)
    from .lifecycle import unregister
    unregister()
