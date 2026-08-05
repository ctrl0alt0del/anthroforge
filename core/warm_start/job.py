import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .model import WarmInvalidationReason, WarmUpdateStatus

WARM_JOB_VERSION = 1


@dataclass(frozen=True)
class WarmJobSpec:
    version: int
    root_name: str
    mode: str
    job_dir: str
    source_path: str
    skin_result_path: str
    topology_result_path: str
    summary_path: str
    status_path: str
    log_path: str
    cancel_path: str


def atomic_json(path, payload):
    target = Path(path)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _replace_with_retry(temporary, target)


def _replace_with_retry(temporary, target, attempts=8):
    for index in range(int(attempts)):
        try:
            os.replace(temporary, target); return
        except PermissionError:
            if index + 1 == attempts:
                raise
            time.sleep(0.005 * (index + 1))


def write_job(spec):
    atomic_json(Path(spec.job_dir) / "job.json", asdict(spec))


def read_job(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if int(payload.get("version", -1)) != WARM_JOB_VERSION:
        raise ValueError("Unsupported coordinated update protocol.")
    return WarmJobSpec(**payload)


def write_status(path, status):
    atomic_json(path, asdict(status))


def read_status(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return WarmUpdateStatus(True, "Waiting", 0.0)
    payload["warnings"] = tuple(payload.get("warnings", ()))
    payload["reason"] = WarmInvalidationReason(payload.get("reason", "NONE"))
    return WarmUpdateStatus(**payload)


def write_summary(path, payload):
    atomic_json(path, payload)


def read_summary(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
