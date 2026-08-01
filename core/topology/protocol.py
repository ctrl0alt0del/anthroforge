import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path

import numpy as np

from .constants import PROTOCOL_VERSION
from .model import (
    SymmetryPlane, TopologyCapture, TopologyGuide, TopologyJobSpec,
    TopologyJobStatus, TopologyResult, TopologyValidationReport,
)
from .settings import settings_from_payload, settings_payload


def _atomic_path(path):
    target = Path(path)
    return target, target.with_name(f".{target.name}.{os.getpid()}.tmp")


def atomic_json(path, payload):
    target, temporary = _atomic_path(path)
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temporary, target)


def atomic_npz(path, **arrays):
    target, temporary = _atomic_path(path)
    with temporary.open("wb") as handle:
        np.savez(handle, **arrays)
    os.replace(temporary, target)


def read_json(path, fallback=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return fallback


def write_status(path, status):
    payload = asdict(status) if isinstance(status, TopologyJobStatus) else dict(status)
    atomic_json(path, payload)


def read_status(path):
    payload = read_json(path, {}) or {}
    fields = TopologyJobStatus.__dataclass_fields__
    clean = {key: value for key, value in payload.items() if key in fields}
    clean["warnings"] = tuple(clean.get("warnings", ()))
    return TopologyJobStatus(**clean)


def write_job(spec):
    atomic_json(Path(spec.job_dir) / "job.json", asdict(spec))


def read_job(path):
    payload = read_json(path)
    if not payload or int(payload.get("protocol_version", -1)) != PROTOCOL_VERSION:
        raise ValueError("Unsupported or missing topology job protocol.")
    return TopologyJobSpec(**payload)


def _guide_meta(guide):
    return {key: getattr(guide, key) for key in (
        "guide_index", "fiber_id", "object_name", "mirror_role")}


def _guide_offsets(guides):
    return np.asarray([0, *np.cumsum([len(item.points) for item in guides])], dtype=np.int64)


def _plane_arrays(plane):
    if plane is None:
        return np.zeros(3), np.zeros(3)
    return np.asarray(plane.origin), np.asarray(plane.normal)


def write_capture(path, capture):
    origin, normal = _plane_arrays(capture.plane)
    points = [np.asarray(item.points, dtype=np.float64) for item in capture.guides]
    atomic_npz(path, **_capture_payload(capture, points, origin, normal))


def _capture_payload(capture, points, origin, normal):
    return {
        "protocol_version": np.asarray([PROTOCOL_VERSION], dtype=np.int32),
        "root_name": np.asarray(capture.root_name), "input_hash": np.asarray(capture.input_hash),
        "vertices": np.asarray(capture.vertices, dtype=np.float64),
        "triangles": np.asarray(capture.triangles, dtype=np.int32),
        "guide_points": _concat(points), "guide_offsets": _guide_offsets(capture.guides),
        "guide_metadata": np.asarray(json.dumps([_guide_meta(x) for x in capture.guides])),
        "lower": np.asarray(capture.lower), "upper": np.asarray(capture.upper),
        "plane_origin": origin, "plane_normal": normal,
        "settings": np.asarray(json.dumps(settings_payload(capture.settings), sort_keys=True)),
        "warnings": np.asarray(json.dumps(list(capture.warnings))),
    }


def _concat(arrays):
    return np.concatenate(arrays) if arrays else np.empty((0, 3), dtype=np.float64)


def _check_protocol(data):
    version = int(data["protocol_version"][0])
    if version != PROTOCOL_VERSION:
        raise ValueError(f"Unsupported topology protocol {version}.")


def read_capture(path):
    with np.load(path, allow_pickle=False) as data:
        _check_protocol(data)
        guides = _read_guides(data)
        settings = settings_from_payload(json.loads(str(data["settings"])))
        plane = _read_plane(data, settings)
        return TopologyCapture(
            str(data["root_name"]), data["vertices"].copy(), data["triangles"].copy(),
            guides, data["lower"].copy(), data["upper"].copy(), str(data["input_hash"]),
            settings, plane, tuple(json.loads(str(data["warnings"]))),
        )


def _read_guides(data):
    metadata = json.loads(str(data["guide_metadata"]))
    offsets, points = data["guide_offsets"], data["guide_points"]
    return tuple(TopologyGuide(**item, points=points[offsets[i]:offsets[i + 1]].copy())
                 for i, item in enumerate(metadata))


def _read_plane(data, settings):
    if settings.symmetry_mode == "NONE":
        return None
    return SymmetryPlane(data["plane_origin"].copy(), data["plane_normal"].copy())


def write_result(path, result):
    report = {} if result.validation is None else asdict(result.validation)
    atomic_npz(path, protocol_version=np.asarray([PROTOCOL_VERSION], dtype=np.int32),
               vertices=np.asarray(result.vertices, dtype=np.float32),
               quads=np.asarray(result.quads, dtype=np.int32),
               face_regions=np.asarray(result.face_regions, dtype=np.int32),
               guide_indices=np.asarray(result.guide_indices, dtype=np.int32),
               statistics=np.asarray(json.dumps(result.statistics)),
               validation=np.asarray(json.dumps(report)))


def read_result(path):
    with np.load(path, allow_pickle=False) as data:
        _check_protocol(data)
        report = TopologyValidationReport(**json.loads(str(data["validation"])))
        return TopologyResult(data["vertices"].copy(), data["quads"].copy(),
                              data["face_regions"].copy(), data["guide_indices"].copy(),
                              json.loads(str(data["statistics"])), report)


def capture_hash(root_name, vertices, triangles, guides, settings, plane):
    digest = hashlib.sha256(str(root_name).encode("utf-8"))
    digest.update(json.dumps(settings_payload(settings), sort_keys=True).encode("utf-8"))
    _update_array(digest, vertices); _update_array(digest, triangles)
    if plane is not None:
        _update_array(digest, plane.origin); _update_array(digest, plane.normal)
    for guide in guides:
        digest.update(json.dumps(_guide_meta(guide), sort_keys=True).encode("utf-8"))
        _update_array(digest, guide.points)
    return digest.hexdigest()


def _update_array(digest, values):
    digest.update(np.ascontiguousarray(values).view(np.uint8))
