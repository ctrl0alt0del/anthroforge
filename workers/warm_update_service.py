import json
import os
import sys
import time
from pathlib import Path

ADDON_ROOT = Path(__file__).resolve().parents[1]
for entry in (str(ADDON_ROOT.parent), str(ADDON_ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)



def service_argument():
    args = sys.argv[sys.argv.index("--") + 1:]
    return Path(args[args.index("--service") + 1])


def atomic_json(path, payload):
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(temporary, path)


def _requests(folder):
    return sorted(folder.glob("request-*.json"), key=lambda path: path.name)


def _claim(path):
    claimed = path.with_suffix(".working")
    try:
        os.replace(path, claimed); return claimed
    except OSError:
        return None


def _run_request(path):
    from workers.warm_update_worker import fail_job
    job_dir = Path(json.loads(path.read_text(encoding="utf-8"))["job_dir"])
    try:
        _run_job(job_dir)
    except Exception as error:
        fail_job(job_dir, error)
    finally:
        path.unlink(missing_ok=True)


def _run_job(job_dir):
    from core.warm_start.job import read_job
    spec = read_job(job_dir / "job.json")
    if spec.mode == "INITIALIZE_DEFORMATION":
        from workers.deformation_reference import run_reference_job
        run_reference_job(job_dir); return
    if spec.mode == "DEFORM":
        from workers.final_skin import run_final_job
        run_final_job(job_dir); return
    if Path(spec.request_path).exists():
        from workers.warm_update_array import run_array_job
        run_array_job(job_dir); return
    from workers.warm_update_worker import run_job
    run_job(job_dir)


def _pulse(folder):
    atomic_json(folder / "heartbeat.json", {"pid": os.getpid(), "time": time.time()})


def run_service(folder):
    folder.mkdir(parents=True, exist_ok=True)
    from adapters.draft_skin.vendor import ensure_worker_dependencies
    ensure_worker_dependencies(); atomic_json(folder / "ready.json", {"pid": os.getpid()})
    while not (folder / "shutdown.request").exists():
        requests = _requests(folder)
        if requests:
            claimed = _claim(requests[0])
            if claimed is not None:
                _run_request(claimed)
        _pulse(folder); time.sleep(0.025)


if __name__ == "__main__":
    run_service(service_argument())
