"""Per-root services reuse the coordinated worker transport and result protocol."""
from pathlib import Path
import time
import tempfile
from ..warm_update import jobs as transport
from ...core.warm_start.job import write_job, write_status
from ...core.warm_start.model import WarmUpdateStatus

SERVICES, ACTIVE = {}, {}


def start(key, root, binary, prepare, options, mode="DEFORM"):
    if key in ACTIVE: raise RuntimeError("A deformation worker is already active for this root.")
    spec = transport._new_spec(root.name,mode,options)
    prepare(spec); write_job(spec)
    write_status(spec.status_path,WarmUpdateStatus(True,"Queued",0.,state="PENDING"))
    service = SERVICES.get(key)
    if service is None or service[0].poll() is not None:
        from .resources import enforce, release
        if service is not None: release(service[0])
        folder = Path(tempfile.mkdtemp(prefix="anthroforge_deformation_service_"))
        service = transport._launch_service(folder,binary),folder; SERVICES[key] = service
        enforce(service[0])
    job = transport.RunningWarmJob(key,spec,service[0],binary)
    ACTIVE[key] = job; transport._queue_request(service[1],spec)
    return job


def poll(key):
    from ...core.warm_start.job import read_status
    job = ACTIVE[key]; status = read_status(job.spec.status_path)
    if getattr(job,"cancelled_at",None) and time.monotonic()-job.cancelled_at>2:
        if job.process.poll() is None: job.process.terminate()
        return WarmUpdateStatus(False,"Cancelled",0.,"Update cancelled; previous mesh retained.",state="CANCELLED",cancelled=True)
    if job.process.poll() is not None and status.state in {"PENDING","RUNNING"}:
        return WarmUpdateStatus(False,"Failed",0.,"Native worker exited; previous mesh retained.",state="FAILED")
    return status


def cancel(key):
    job = ACTIVE.get(key)
    if job:
        Path(job.spec.cancel_path).touch(); job.cancelled_at = time.monotonic()


def shutdown():
    for key in tuple(ACTIVE): cancel(key)
    for process, folder in SERVICES.values():
        Path(folder,"shutdown.request").touch()
        if process.poll() is None: process.terminate()
        from .resources import release
        release(process)
    SERVICES.clear(); ACTIVE.clear()
