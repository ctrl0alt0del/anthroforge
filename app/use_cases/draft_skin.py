from ..queries.root import root_for_context
from .results import failure, success


def start_generation(context):
    root = root_for_context(context)
    if root is None:
        return failure("Create an AnthroForge root before generating skin.")
    if _jobs().active_job(context.scene) is not None or _topology_running(context.scene):
        return failure("A draft skin job is already running in this scene.", "WARNING")
    try:
        job = _jobs().start_job(context.scene, root.name, _binary_path(), _save_copy)
        _set_scene_status(context.scene, "Starting", 0.0, "Draft skin worker is starting.", True)
        return success("Draft skin generation started.", value=job)
    except Exception as error:
        return failure(str(error))


def poll_generation(context):
    status = _jobs().poll_job(context.scene)
    _set_scene_status(context.scene, status.stage, status.progress, status.message, not _terminal(status))
    return status


def complete_generation(context, status):
    if status.state != "SUCCEEDED":
        return _finish_failure(context, status)
    try:
        job = _jobs().active_job(context.scene)
        if job is None:
            raise RuntimeError("The completed draft-skin job is no longer available.")
        result = _validated_result(job)
        obj = _import_result(context, job, result)
        return _generation_success(context, result, obj)
    except Exception as error:
        _jobs().finish_job(context.scene, False)
        return failure(str(error))


def _validated_result(job):
    result = _jobs().result_for_job(job)
    from ...core.mesh_issues import require_mesh
    require_mesh(result.vertices, result.triangles, 3)
    return result


def _import_result(context, job, result):
    from ...adapters.job_revision import require_current
    require_current(job, context.scene)
    root = context.scene.objects.get(job.spec.root_name)
    if root is None or not root.get("anthroforge_root"):
        raise RuntimeError("The source AnthroForge root is no longer in this scene.")
    source_map = result.statistics.get("source_map", [])
    return _output().replace_draft_skin(context.scene, root, result, source_map)


def _finish_failure(context, status):
    _jobs().finish_job(context.scene, False)
    message = status.message or "Draft skin generation failed."
    _set_scene_status(context.scene, status.stage, status.progress, message, False)
    return failure(message, "WARNING" if status.cancelled else "ERROR")


def cancel_generation(context):
    changed = _jobs().cancel_job(context.scene)
    if changed:
        _set_scene_status(context.scene, "Cancelling", 0.0, "Cancelling draft skin generation.", True)
    return success("Cancellation requested.") if changed else failure("No draft skin job is running.", "WARNING")


def force_terminate(context):
    _jobs().terminate_job(context.scene)


def abort_generation(context):
    _jobs().cancel_job(context.scene)
    _jobs().terminate_job(context.scene)
    _jobs().finish_job(context.scene, False)
    _set_scene_status(context.scene, "Cancelled", 0.0, "Draft skin generation cancelled.", False)


def diagnostic_path(scene):
    return _jobs().diagnostic_path(scene)


def _terminal(status):
    return status.state in {"SUCCEEDED", "FAILED", "CANCELLED"}


def _set_scene_status(scene, stage, progress, message, running):
    scene.af_draft_skin_stage = str(stage or "")
    scene.af_draft_skin_progress = min(1.0, max(0.0, float(progress)))
    scene.af_draft_skin_message = str(message or "")
    scene.af_draft_skin_running = bool(running)
    scene.af_draft_skin_diagnostic = diagnostic_path(scene)


def _jobs():
    try:
        from ...adapters.draft_skin import jobs
    except ImportError:
        from adapters.draft_skin import jobs
    return jobs


def _topology_running(scene):
    try:
        from ...adapters.topology.jobs import active_job
    except ImportError:
        from adapters.topology.jobs import active_job
    try:
        from ...adapters.warm_update.jobs import active_job as warm_job
    except ImportError:
        from adapters.warm_update.jobs import active_job as warm_job
    return active_job(scene) is not None or warm_job(scene) is not None


def _output():
    try:
        from ...adapters.draft_skin import output
    except ImportError:
        from adapters.draft_skin import output
    return output


def _binary_path():
    import bpy
    return bpy.app.binary_path


def _save_copy(path):
    import bpy
    bpy.ops.wm.save_as_mainfile(filepath=str(path), copy=True, compress=False)


def _generation_success(context, result, obj):
    issues = result.statistics.get("issues", ())
    _jobs().finish_job(context.scene, not issues)
    message = f"Draft skin generated with {len(issues)} warning(s)." if issues else "Draft skin generated."
    _set_scene_status(context.scene, "Complete", 1.0, message, False)
    return success(message, "WARNING" if issues else "INFO", obj)
