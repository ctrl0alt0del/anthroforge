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


_ACTIVE, _LAST_DIAGNOSTIC = {}, {}


def scene_key(scene):
    return int(scene.as_pointer())


def active_job(scene):
    return _ACTIVE.get(scene_key(scene))


def start_job(scene, root_name, mode, blender_binary, save_copy):
    key = scene_key(scene)
    if key in _ACTIVE:
        raise RuntimeError("A coordinated AnthroForge update is already running.")
    _cleanup_last(key); spec = _new_spec(root_name, mode)
    try:
        process = _prepare(spec, blender_binary, save_copy)
    except Exception:
        _LAST_DIAGNOSTIC[key] = spec.log_path; raise
    job = RunningWarmJob(key, spec, process); _ACTIVE[key] = job
    return job


def poll_job(scene):
    job = active_job(scene)
    if job is None:
        return WarmUpdateStatus(True, "Idle", 0.0, state="IDLE")
    status = read_status(job.spec.status_path)
    if job.process.poll() is not None and status.state in {"PENDING", "RUNNING"}:
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
    if job.process.poll() is None:
        job.process.terminate()
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
    job = active_job(scene)
    if job is not None and job.process.poll() is None:
        job.process.terminate()


def shutdown_jobs():
    for job in tuple(_ACTIVE.values()):
        if job.process.poll() is None:
            job.process.terminate()
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
                       value("status.json"), value("job.log"), value("cancel.request"))


def _prepare(spec, binary, save_copy):
    save_copy(spec.source_path); write_job(spec)
    write_status(spec.status_path, WarmUpdateStatus(True, "Starting", 0.0, state="PENDING"))
    return _launch(spec, binary)


def _launch(spec, binary):
    worker = Path(__file__).resolve().parents[2] / "workers" / "warm_update_worker.py"
    if not worker.is_file():
        raise FileNotFoundError("The bundled coordinated update worker is missing.")
    command = [str(binary), "--background", "--factory-startup", "--python",
               str(worker), "--", "--job", spec.job_dir]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with open(spec.log_path, "a", encoding="utf-8") as log:
        return subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)


def _cleanup_last(key):
    path = _LAST_DIAGNOSTIC.pop(key, "")
    if path:
        shutil.rmtree(Path(path).parent, ignore_errors=True)
