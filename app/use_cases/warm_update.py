from ..queries.root import root_for_context
from .results import failure, success


def start_update(context, mode="AUTO", topology_update=None):
    root = root_for_context(context)
    if root is None:
        return failure("Create an AnthroForge root before updating outputs.")
    if mode == "AUTO" and root.get("af_deformation_reference") is not None:
        from ...adapters.deformation.runtime import enqueue
        enqueue(root,context.scene,True); return success("Final-skin deformation queued.")
    return _start_legacy(context,root,mode,topology_update)


def _start_legacy(context, root, mode, topology_update):
    if _any_job(context.scene):
        return failure("Another AnthroForge generation job is already running.", "WARNING")
    try:
        _require_legacy_root(root,mode)
        prepare = _prepare_callback(context, root, mode)
        job = _jobs().start_job(context.scene, root.name, mode, _binary_path(), prepare, topology_update)
        _set_status(context.scene, "Starting", 0.0, "Update worker is starting.", True)
        return success("Skin and topology update started.", value=job)
    except Exception as error:
        return failure(str(error))


def _require_legacy_root(root, mode="AUTO"):
    getter = getattr(root,"get",None)
    if callable(getter) and getter("af_deformation_reference") is not None and mode != "FORCE_FULL":
        raise RuntimeError("Use Update Now for LE/FAST deformation or explicitly Rebuild Skin & Topology.")


def poll_update(context):
    status = _jobs().poll_job(context.scene)
    _set_status(context.scene, status.stage, status.progress, status.message, not _terminal(status))
    return status


def complete_update(context, status):
    if status.state not in {"SUCCEEDED", "PARTIAL"}:
        return _finish_failure(context, status)
    try:
        return _publish_completed(context)
    except Exception as error:
        _jobs().finish_job(context.scene, False); return failure(str(error))


def cancel_update(context):
    changed = _jobs().cancel_job(context.scene)
    if changed:
        _set_status(context.scene, "Cancelling", 0.0, "Cancelling coordinated update.", True)
    return success("Cancellation requested.") if changed else failure("No update job is running.", "WARNING")


def abort_update(context):
    _jobs().cancel_job(context.scene); _jobs().terminate_job(context.scene)
    _jobs().finish_job(context.scene, False)
    _set_status(context.scene, "Cancelled", 0.0, "Update cancelled.", False)


def _finish_success(context, summary):
    _jobs().finish_job(context.scene, summary.get("state") != "PARTIAL" and not summary.get("issues"))
    scene = context.scene; scene.af_last_update_type = summary.get("update_type", "")
    scene.af_last_update_seconds = float(summary.get("elapsed_seconds", 0.0))
    scene.af_last_update_diagnostic = str(summary.get("fallback_diagnostic", ""))
    _set_status(scene, "Complete", 1.0, _message(summary), False)


def _finish_failure(context, status):
    _jobs().finish_job(context.scene, False)
    message = status.message or "Skin and topology update failed."
    _set_status(context.scene, status.stage, status.progress, message, False)
    return failure(message, "WARNING" if status.cancelled else "ERROR")


def _message(summary):
    if summary.get("state") == "PARTIAL":
        return "Draft skin completed; previous topology retained as stale. " + summary.get("fallback_diagnostic", "")
    kind = summary.get("update_type", "updated").title()
    seconds = float(summary.get("elapsed_seconds", 0.0))
    count = len(summary.get("issues", ()))
    return f"{kind} skin/topology in {seconds:.2f}s." + (f" {count} warning(s)." if count else "")


def _set_status(scene, stage, progress, message, running):
    scene.af_warm_update_stage = str(stage or "")
    scene.af_warm_update_progress = min(1.0, max(0.0, float(progress)))
    scene.af_warm_update_message = str(message or "")
    scene.af_warm_update_running = bool(running)
    scene.af_warm_update_diagnostic = _jobs().diagnostic_path(scene)


def _terminal(status):
    return status.state in {"SUCCEEDED", "PARTIAL", "FAILED", "CANCELLED"}


def _any_job(scene):
    from ...adapters.deformation.jobs import ACTIVE
    if any(job.spec.root_name in scene.objects for job in ACTIVE.values()): return True
    try:
        from ...adapters.draft_skin.jobs import active_job as skin_job
        from ...adapters.topology.jobs import active_job as topology_job
    except ImportError:
        from adapters.draft_skin.jobs import active_job as skin_job
        from adapters.topology.jobs import active_job as topology_job
    return bool(_jobs().active_job(scene) or skin_job(scene) or topology_job(scene))


def _jobs():
    try:
        from ...adapters.warm_update import jobs
    except ImportError:
        from adapters.warm_update import jobs
    return jobs


def _output():
    try:
        from ...adapters.warm_update import output
    except ImportError:
        from adapters.warm_update import output
    return output


def _binary_path():
    import bpy
    return bpy.app.binary_path


def _save_copy(path):
    import bpy
    bpy.ops.wm.save_as_mainfile(filepath=str(path), copy=True, compress=False)


def _prepare_callback(context, root, mode):
    if mode == "FORCE_FULL":
        from ...adapters.deformation.rebuild import capture
        return lambda spec: capture(context,root,spec)
    if mode == "PREPARE":
        return lambda spec: _save_copy(spec.source_path)
    try:
        from ...adapters.warm_update.capture import prepare_array_job
    except ImportError:
        from adapters.warm_update.capture import prepare_array_job
    return lambda spec: prepare_array_job(context, root, spec)


def _publish_completed(context):
    job = _jobs().active_job(context.scene)
    if job is None:
        raise RuntimeError("The coordinated update job is unavailable.")
    from ...adapters.job_revision import require_current
    require_current(job, context.scene)
    skin, topology, summary = _jobs().result_for_job(job)
    root = context.scene.objects.get(job.spec.root_name)
    if root is None or not root.get("anthroforge_root"):
        raise RuntimeError("The source AnthroForge root is no longer in this scene.")
    outputs = _publish_outputs(context,root,job,skin,topology)
    from ...adapters.mesh_issues import publish_summary
    publish_summary(context.scene, root, summary)
    _finish_success(context, summary)
    return success(_message(summary), "WARNING" if summary.get("issues") else "INFO", outputs)


def _publish_outputs(context, root, job, skin, topology):
    if job.spec.mode == "FORCE_FULL":
        from pathlib import Path
        from ...adapters.deformation.construction import publish
        if topology is None: raise RuntimeError("Rebuild produced no usable topology; previous output retained.")
        if not Path(job.spec.job_dir,"reference.txt").exists() and root.get("af_deformation_reference") is None:
            return _output().replace_outputs(context.scene,root,skin,topology)
        return publish(context.scene,root,topology,job.spec.job_dir)
    return _output().replace_outputs(context.scene,root,skin,topology)
