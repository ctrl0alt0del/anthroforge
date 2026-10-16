"""Isolated, bounded construction-reference preparation for generated topology."""
import sys
import json
from pathlib import Path
from types import SimpleNamespace
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT.parent)]
from adapters.topology.vendor import ensure_worker_dependencies
ensure_worker_dependencies()
import numpy as np
from workers.deformation_reference import build
from core.topology.protocol import read_result
from core.deformation.serialization import encode, decode


def run(folder):
    request = json.loads((folder/"reference_request.json").read_text())
    spec = SimpleNamespace(cancel_path=request["cancel"], topology_update=dict(settings=request["settings"]))
    result = read_result(folder/"reference_input.npz")
    with np.load(folder/"reference_source.npz", allow_pickle=False) as source:
        reference = build(spec, result, request["records"], source)
    payload = encode(reference)
    if decode(payload).signature != reference.signature: raise ValueError("Reference serialization failed.")
    (folder/"reference.txt").write_text(payload, encoding="ascii")


if __name__ == "__main__": run(Path(sys.argv[sys.argv.index("--")+1]))
