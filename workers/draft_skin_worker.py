import sys
import traceback
from dataclasses import replace
from pathlib import Path


ADDON_ROOT = Path(__file__).resolve().parents[1]
for entry in (str(ADDON_ROOT.parent), str(ADDON_ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from core.draft_skin.model import SkinJobStatus
from core.draft_skin.protocol import read_job, write_capture, write_job, write_result, write_status
from core.draft_skin.status import SkinCancelled
from adapters.draft_skin.vendor import ensure_worker_dependencies


def job_argument():
    args = sys.argv[sys.argv.index("--") + 1 :]
    return Path(args[args.index("--job") + 1])


def cancelled(spec):
    return Path(spec.cancel_path).exists()


def status_writer(spec):
    def update(stage, progress, message=""):
        status = SkinJobStatus("RUNNING", stage, progress, message)
        write_status(spec.status_path, status)
    return update


def finish_status(spec, state, message="", warnings=(), was_cancelled=False):
    progress = 1.0 if state == "SUCCEEDED" else 0.0
    status = SkinJobStatus(state, state.title(), progress, message, tuple(warnings), was_cancelled)
    write_status(spec.status_path, status)


def run_job(job_dir):
    spec = read_job(job_dir / "job.json")
    status_writer(spec)("Dependencies", 0.01, "Validating packaged worker dependencies.")
    ensure_worker_dependencies()
    capture = _bake_and_capture(spec)
    spec = replace(spec, input_hash=capture.input_hash)
    write_job(spec)
    write_capture(spec.input_path, capture)
    from core.draft_skin.solver import solve_capture
    result = solve_capture(capture, status_writer(spec), lambda: cancelled(spec))
    write_result(spec.result_path, result)
    finish_status(spec, "SUCCEEDED", "Draft skin generated.", capture.warnings)


def _bake_and_capture(spec):
    finish_status(spec, "RUNNING", "Loading scene for background bake.")
    import bpy
    import anthroforge
    if not hasattr(bpy.types.Object, "af_scp_system"):
        anthroforge.register()
    bpy.ops.wm.open_mainfile(filepath=spec.source_path)
    return _capture_scene(spec)


def _capture_scene(spec):
    import bpy
    from app.runtime_api import sync_context
    from adapters.draft_skin.capture import capture_skin
    root = bpy.context.scene.objects.get(spec.root_name)
    if root is None or not root.get("anthroforge_root"):
        raise RuntimeError(f"The background scene has no AF_ROOT named {spec.root_name}.")
    status_writer(spec)("Baking", 0.02, "Finalizing SCP and VCP runtime surfaces.")
    sync_context(bpy.context, bake=True, source="draft_skin", event_type="BAKE")
    bpy.context.view_layer.update()
    status_writer(spec)("Capturing", 0.04, "Capturing evaluated contributors.")
    return capture_skin(root, bpy.context.scene, bpy.context.evaluated_depsgraph_get())


def append_failure(job_dir, text):
    path = job_dir / "job.log"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text.rstrip() + "\n")


def fail_job(job_dir, error):
    append_failure(job_dir, traceback.format_exc())
    spec = read_job(job_dir / "job.json")
    is_cancel = isinstance(error, SkinCancelled)
    state = "CANCELLED" if is_cancel else "FAILED"
    finish_status(spec, state, str(error), was_cancelled=is_cancel)


def main():
    job_dir = job_argument()
    try:
        run_job(job_dir)
    except Exception as error:
        fail_job(job_dir, error)
        if not isinstance(error, SkinCancelled):
            raise


if __name__ == "__main__":
    main()
