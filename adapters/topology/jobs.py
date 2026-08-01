import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

try:
    from ...core.topology.constants import PROTOCOL_VERSION, SOLVER_VERSION
    from ...core.topology.model import TopologyJobSpec, TopologyJobStatus
    from ...core.topology.protocol import read_result, read_status, write_job, write_status
except ImportError:
    from core.topology.constants import PROTOCOL_VERSION, SOLVER_VERSION
    from core.topology.model import TopologyJobSpec, TopologyJobStatus
    from core.topology.protocol import read_result, read_status, write_job, write_status


@dataclass
class RunningTopologyJob:
    scene_key: int
    spec: TopologyJobSpec
    process: object


_ACTIVE = {}
_LAST_DIAGNOSTIC = {}


def scene_key(scene):
    return int(scene.as_pointer())


def active_job(scene):
    return _ACTIVE.get(scene_key(scene))


def start_job(scene, root_name, blender_binary, save_copy):
    key = scene_key(scene)
    if key in _ACTIVE:
        raise RuntimeError("A topology job is already running in this scene.")
    _cleanup_last(key)
    spec = _new_spec(root_name)
    try:
        process = _prepare_process(spec, blender_binary, save_copy)
    except Exception:
        _LAST_DIAGNOSTIC[key] = spec.log_path
        raise
    job = RunningTopologyJob(key, spec, process)
    _ACTIVE[key] = job
    return job


def _new_spec(root_name):
    folder = Path(tempfile.mkdtemp(prefix="anthroforge_topology_"))
    value = lambda name: str(folder / name)
    return TopologyJobSpec(PROTOCOL_VERSION, SOLVER_VERSION, str(root_name), "", str(folder),
                           value("source.blend"), value("input.npz"), value("result.npz"),
                           value("status.json"), value("job.log"), value("cancel.request"))


def _prepare_process(spec, binary, save_copy):
    save_copy(spec.source_path)
    write_job(spec)
    write_status(spec.status_path, TopologyJobStatus())
    return _launch(spec, binary)


def _launch(spec, binary):
    worker = Path(__file__).resolve().parents[2] / "workers" / "topology_worker.py"
    if not worker.is_file():
        raise FileNotFoundError("The bundled topology worker is missing.")
    command = [str(binary), "--background", "--factory-startup", "--python", str(worker),
               "--", "--job", spec.job_dir]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    log = open(spec.log_path, "a", encoding="utf-8")
    try:
        return subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
    finally:
        log.close()


def poll_job(scene):
    job = active_job(scene)
    if job is None:
        return TopologyJobStatus("IDLE", "Idle", 0.0, "")
    status = read_status(job.spec.status_path)
    if job.process.poll() is not None and status.state in {"PENDING", "RUNNING"}:
        return TopologyJobStatus("FAILED", "Failed", 0.0, "Topology worker exited unexpectedly.")
    return status


def cancel_job(scene):
    job = active_job(scene)
    if job is None:
        return False
    Path(job.spec.cancel_path).touch()
    write_status(job.spec.status_path, TopologyJobStatus(
        "CANCELLED", "Cancelled", 0.0, "Topology generation cancelled.", (), True))
    if job.process.poll() is None:
        job.process.terminate()
    return True


def terminate_job(scene):
    job = active_job(scene)
    if job is not None and job.process.poll() is None:
        job.process.terminate()


def result_for_job(job):
    return read_result(job.spec.result_path)


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
    return job.spec.log_path if job is not None else _LAST_DIAGNOSTIC.get(scene_key(scene), "")


def _cleanup_last(key):
    path = _LAST_DIAGNOSTIC.pop(key, "")
    if path:
        shutil.rmtree(Path(path).parent, ignore_errors=True)


def shutdown_jobs():
    for job in tuple(_ACTIVE.values()):
        if job.process.poll() is None:
            job.process.terminate()
        shutil.rmtree(job.spec.job_dir, ignore_errors=True)
    _ACTIVE.clear()
    for key in tuple(_LAST_DIAGNOSTIC):
        _cleanup_last(key)
