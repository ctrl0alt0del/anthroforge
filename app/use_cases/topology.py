from ..queries.root import root_for_context
from .results import failure, success


def start_generation(context):
    root = root_for_context(context)
    if root is None:
        return failure("Create an AnthroForge root before generating topology.")
    if _other_job_running(context.scene):
        return failure("Another AnthroForge generation job is already running.", "WARNING")
    try:
        job = _jobs().start_job(context.scene, root.name, _binary_path(), _save_copy)
        _set_status(context.scene, "Starting", 0.0, "Topology worker is starting.", True)
        return success("Topology generation started.", value=job)
    except Exception as error:
        return failure(str(error))


def poll_generation(context):
    status = _jobs().poll_job(context.scene)
    _set_status(context.scene, status.stage, status.progress, status.message, not _terminal(status))
    return status


def complete_generation(context, status):
    if status.state != "SUCCEEDED":
        return _finish_failure(context, status)
    try:
        return _complete_success(context)
    except Exception as error:
        _jobs().finish_job(context.scene, False)
        return failure(str(error))


def _complete_success(context):
    job = _jobs().active_job(context.scene)
    if job is None:
        raise RuntimeError("The completed topology job is no longer available.")
    result = _jobs().result_for_job(job)
    if result.validation is None or not result.validation.valid:
        raise ValueError("The worker returned invalid topology.")
    obj = _import_result(context, job, result)
    _jobs().finish_job(context.scene, True)
    warnings = tuple(result.statistics.get("warnings", ()))
    message = _success_message(warnings)
    _set_status(context.scene, "Complete", 1.0, message, False)
    return success(message, "WARNING" if warnings else "INFO", obj)


def _success_message(warnings):
    if not warnings:
        return "Topology generated."
    return f"Topology generated with {len(warnings)} warning(s): {warnings[0]}"


def _import_result(context, job, result):
    root = context.scene.objects.get(job.spec.root_name)
    if root is None or not root.get("anthroforge_root"):
        raise RuntimeError("The source AnthroForge root is no longer in this scene.")
    return _output().replace_topology(context.scene, root, result)


def _finish_failure(context, status):
    _jobs().finish_job(context.scene, False)
    message = status.message or "Topology generation failed."
    _set_status(context.scene, status.stage, status.progress, message, False)
    return failure(message, "WARNING" if status.cancelled else "ERROR")


def cancel_generation(context):
    changed = _jobs().cancel_job(context.scene)
    if changed:
        _set_status(context.scene, "Cancelling", 0.0, "Cancelling topology generation.", True)
    return success("Cancellation requested.") if changed else failure(
        "No topology job is running.", "WARNING")


def abort_generation(context):
    _jobs().cancel_job(context.scene)
    _jobs().terminate_job(context.scene)
    _jobs().finish_job(context.scene, False)
    _set_status(context.scene, "Cancelled", 0.0, "Topology generation cancelled.", False)


def _terminal(status):
    return status.state in {"SUCCEEDED", "FAILED", "CANCELLED"}


def _set_status(scene, stage, progress, message, running):
    scene.af_topology_stage = str(stage or "")
    scene.af_topology_progress = min(1.0, max(0.0, float(progress)))
    scene.af_topology_message = str(message or "")
    scene.af_topology_running = bool(running)
    scene.af_topology_diagnostic = _jobs().diagnostic_path(scene)


def _other_job_running(scene):
    from ...adapters.draft_skin.jobs import active_job as active_skin
    return active_skin(scene) is not None or _jobs().active_job(scene) is not None


def _jobs():
    from ...adapters.topology import jobs
    return jobs


def _output():
    from ...adapters.topology import output
    return output


def _binary_path():
    import bpy
    return bpy.app.binary_path


def _save_copy(path):
    import bpy
    bpy.ops.wm.save_as_mainfile(filepath=str(path), copy=True, compress=False)
