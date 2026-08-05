import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

try:
    from ...core.warm_start.job import (
        WARM_JOB_VERSION, WarmJobSpec, read_status, read_summary, write_job, write_status,
    )
    from ...core.warm_start.model import WarmUpdateStatus
except ImportError:
    from core.warm_start.job import WARM_JOB_VERSION, WarmJobSpec, read_status, read_summary, write_job, write_status
    from core.warm_start.model import WarmUpdateStatus


@dataclass
class RunningWarmJob:
    scene_key: int
    spec: WarmJobSpec
    process: object
    binary: str = ""
    retries: int = 0


_ACTIVE, _LAST_DIAGNOSTIC = {}, {}
_SERVICE = None


def scene_key(scene):
    return int(scene.as_pointer())


def active_job(scene):
    return _ACTIVE.get(scene_key(scene))


def start_job(scene, root_name, mode, blender_binary, prepare_job):
    key = scene_key(scene)
    if key in _ACTIVE:
        raise RuntimeError("A coordinated AnthroForge update is already running.")
    _cleanup_last(key); spec = _new_spec(root_name, mode)
    try:
        process = _prepare(spec, blender_binary, prepare_job)
    except Exception:
        _LAST_DIAGNOSTIC[key] = spec.log_path; raise
    job = RunningWarmJob(key, spec, process, str(blender_binary)); _ACTIVE[key] = job
    return job


def poll_job(scene):
    job = active_job(scene)
    if job is None:
        return WarmUpdateStatus(True, "Idle", 0.0, state="IDLE")
    status = read_status(job.spec.status_path)
    if job.process.poll() is not None and status.state in {"PENDING", "RUNNING"}:
        if _retry_job(job):
            return WarmUpdateStatus(True, "Restarting", status.progress,
                                    "Numerical worker restarted after an unexpected exit.", state="RUNNING")
        return WarmUpdateStatus(False, "Failed", 0.0, "Update worker exited unexpectedly.",
                                state="FAILED")
    return status


def cancel_job(scene):
    job = active_job(scene)
    if job is None:
        return False
    Path(job.spec.cancel_path).touch()
    status = WarmUpdateStatus(False, "Cancelled", 0.0, "Update cancelled.",
                              state="CANCELLED", cancelled=True)
    write_status(job.spec.status_path, status)
    return True


def result_for_job(job):
    try:
        from ...core.draft_skin.protocol import read_result as read_skin
        from ...core.topology.protocol import read_result as read_topology
    except ImportError:
        from core.draft_skin.protocol import read_result as read_skin
        from core.topology.protocol import read_result as read_topology
    summary = read_summary(job.spec.summary_path)
    skin = read_skin(job.spec.skin_result_path) if summary.get("has_skin_result") else None
    topology = read_topology(job.spec.topology_result_path) if summary.get("has_topology_result") else None
    return skin, topology, summary


def finish_job(scene, succeeded):
    job = _ACTIVE.pop(scene_key(scene), None)
    if job is None:
        return
    if succeeded:
        shutil.rmtree(job.spec.job_dir, ignore_errors=True)
    else:
        _LAST_DIAGNOSTIC[job.scene_key] = job.spec.log_path


def diagnostic_path(scene):
    job = active_job(scene)
    return job.spec.log_path if job else _LAST_DIAGNOSTIC.get(scene_key(scene), "")


def terminate_job(scene):
    global _SERVICE
    job = active_job(scene)
    if job is not None and job.process.poll() is None:
        job.process.terminate()
    if _SERVICE is not None:
        shutil.rmtree(_SERVICE[1], ignore_errors=True)
        _SERVICE = None


def shutdown_jobs():
    global _SERVICE
    _stop_service(); _SERVICE = None
    for job in tuple(_ACTIVE.values()):
        shutil.rmtree(job.spec.job_dir, ignore_errors=True)
    _ACTIVE.clear()
    for key in tuple(_LAST_DIAGNOSTIC):
        _cleanup_last(key)


def _new_spec(root_name, mode):
    folder = Path(tempfile.mkdtemp(prefix="anthroforge_update_"))
    value = lambda name: str(folder / name)
    return WarmJobSpec(WARM_JOB_VERSION, str(root_name), str(mode), str(folder),
                       value("source.blend"), value("skin_result.npz"),
                       value("topology_result.npz"), value("summary.json"),
                       value("status.json"), value("job.log"), value("cancel.request"),
                       value("request.json"), value("skin_capture.npz"),
                       value("topology_capture.npz"), value("current_skin.npz"),
                       value("current_topology.npz"))


def _prepare(spec, binary, prepare_job):
    prepare_job(spec); write_job(spec)
    write_status(spec.status_path, WarmUpdateStatus(True, "Starting", 0.0, state="PENDING"))
    process, folder = _ensure_service(binary)
    _queue_request(folder, spec)
    return process


def _launch_service(folder, binary):
    worker = Path(__file__).resolve().parents[2] / "workers" / "warm_update_service.py"
    if not worker.is_file():
        raise FileNotFoundError("The bundled coordinated update service is missing.")
    command = [str(binary), "--background", "--factory-startup", "--python",
               str(worker), "--", "--service", str(folder)]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with open(folder / "service.log", "a", encoding="utf-8") as log:
        return subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)


def _ensure_service(binary):
    global _SERVICE
    if _SERVICE is not None and _SERVICE[0].poll() is None:
        return _SERVICE
    folder = Path(tempfile.mkdtemp(prefix="anthroforge_warm_service_"))
    _SERVICE = (_launch_service(folder, binary), folder)
    return _SERVICE


def _queue_request(folder, spec):
    payload = {"job_dir": spec.job_dir}
    target = folder / f"request-{Path(spec.job_dir).name}.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(__import__("json").dumps(payload), encoding="utf-8")
    os.replace(temporary, target)


def _stop_service():
    if _SERVICE is None:
        return
    process, folder = _SERVICE
    Path(folder, "shutdown.request").touch()
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        process.terminate()
    shutil.rmtree(folder, ignore_errors=True)


def _retry_job(job):
    global _SERVICE
    if job.retries >= 1:
        return False
    old = _SERVICE; job.retries += 1; _SERVICE = None
    if old is not None:
        shutil.rmtree(old[1], ignore_errors=True)
    process, folder = _ensure_service(job.binary)
    job.process = process; _queue_request(folder, job.spec)
    write_status(job.spec.status_path, WarmUpdateStatus(True, "Restarting", 0.0, state="RUNNING"))
    return True


def _cleanup_last(key):
    path = _LAST_DIAGNOSTIC.pop(key, "")
    if path:
        shutil.rmtree(Path(path).parent, ignore_errors=True)
