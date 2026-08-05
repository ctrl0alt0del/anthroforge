from ..queries.root import root_for_context
from .results import failure, success


def start_update(context, mode="AUTO"):
    root = root_for_context(context)
    if root is None:
        return failure("Create an AnthroForge root before updating outputs.")
    if _any_job(context.scene):
        return failure("Another AnthroForge generation job is already running.", "WARNING")
    try:
        job = _jobs().start_job(context.scene, root.name, mode, _binary_path(), _save_copy)
        _set_status(context.scene, "Starting", 0.0, "Update worker is starting.", True)
        return success("Skin and topology update started.", value=job)
    except Exception as error:
        return failure(str(error))


def poll_update(context):
    status = _jobs().poll_job(context.scene)
    _set_status(context.scene, status.stage, status.progress, status.message, not _terminal(status))
    return status


def complete_update(context, status):
    if status.state != "SUCCEEDED":
        return _finish_failure(context, status)
    try:
        job = _jobs().active_job(context.scene)
        if job is None:
            raise RuntimeError("The coordinated update job is unavailable.")
        skin, topology, summary = _jobs().result_for_job(job)
        root = context.scene.objects.get(job.spec.root_name)
        if root is None or not root.get("anthroforge_root"):
            raise RuntimeError("The source AnthroForge root is no longer in this scene.")
        outputs = _output().replace_outputs(context.scene, root, skin, topology)
        _finish_success(context, summary); return success(_message(summary), value=outputs)
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
    _jobs().finish_job(context.scene, True)
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
    kind = summary.get("update_type", "updated").title()
    seconds = float(summary.get("elapsed_seconds", 0.0))
    return f"{kind} skin/topology in {seconds:.2f}s."


def _set_status(scene, stage, progress, message, running):
    scene.af_warm_update_stage = str(stage or "")
    scene.af_warm_update_progress = min(1.0, max(0.0, float(progress)))
    scene.af_warm_update_message = str(message or "")
    scene.af_warm_update_running = bool(running)
    scene.af_warm_update_diagnostic = _jobs().diagnostic_path(scene)


def _terminal(status):
    return status.state in {"SUCCEEDED", "FAILED", "CANCELLED"}


def _any_job(scene):
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
