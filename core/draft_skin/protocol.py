import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path

import numpy as np

from .constants import PROTOCOL_VERSION
from .model import SkinCapture, SkinJobSpec, SkinJobStatus, SkinResult, SkinSource, SkinValidationReport
from .settings import DEFAULT_SETTINGS, settings_from_payload, settings_payload
from ..warm_start.model import SkinWarmBinding


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
    payload = asdict(status) if isinstance(status, SkinJobStatus) else dict(status)
    atomic_json(path, payload)


def read_status(path):
    payload = read_json(path, {}) or {}
    fields = SkinJobStatus.__dataclass_fields__
    clean = {key: value for key, value in payload.items() if key in fields}
    clean["warnings"] = tuple(clean.get("warnings", ()))
    return SkinJobStatus(**clean)


def write_job(spec):
    atomic_json(Path(spec.job_dir) / "job.json", asdict(spec))


def read_job(path):
    payload = read_json(path)
    if not payload or int(payload.get("protocol_version", -1)) != PROTOCOL_VERSION:
        raise ValueError("Unsupported or missing draft-skin job protocol.")
    return SkinJobSpec(**payload)


def _source_metadata(source):
    return {
        "source_index": int(source.source_index),
        "entity_type": str(source.entity_type),
        "entity_id": str(source.entity_id),
        "mirror_role": str(source.mirror_role),
        "object_name": str(source.object_name),
    }


def _capture_arrays(capture):
    vertices = [np.asarray(item.vertices, dtype=np.float64) for item in capture.sources]
    triangles = [np.asarray(item.triangles, dtype=np.int32) for item in capture.sources]
    collagen = [_source_collagen(item, len(vertices[i])) for i, item in enumerate(capture.sources)]
    return vertices, triangles, collagen


def _source_collagen(source, count):
    if source.collagen is None:
        return np.ones(int(count), dtype=np.float32)
    return np.asarray(source.collagen, dtype=np.float32)


def _offsets(arrays):
    return np.asarray([0, *np.cumsum([len(item) for item in arrays])], dtype=np.int64)


def write_capture(path, capture):
    vertices, triangles, collagen = _capture_arrays(capture)
    payload = _capture_payload(capture, vertices, triangles, collagen)
    atomic_npz(path, **payload)


def _capture_payload(capture, vertices, triangles, collagen):
    metadata = json.dumps([_source_metadata(item) for item in capture.sources])
    payload = _capture_header(capture, metadata)
    payload.update({
        "vertices": _concat(vertices, np.float64, (0, 3)),
        "triangles": _concat(triangles, np.int32, (0, 3)),
        "collagen": _concat(collagen, np.float32, (0,)),
        "vertex_offsets": _offsets(vertices),
        "triangle_offsets": _offsets(triangles),
    })
    return payload


def _capture_header(capture, metadata):
    return {
        "protocol_version": np.asarray([PROTOCOL_VERSION], dtype=np.int32),
        "root_name": np.asarray(capture.root_name),
        "input_hash": np.asarray(capture.input_hash),
        "resolution": np.asarray([capture.resolution], dtype=np.int32),
        "voxel_size": np.asarray([capture.voxel_size], dtype=np.float64),
        "lower": np.asarray(capture.lower, dtype=np.float64),
        "upper": np.asarray(capture.upper, dtype=np.float64),
        "metadata": np.asarray(metadata),
        "warnings": np.asarray(json.dumps(list(capture.warnings))),
        "settings": np.asarray(json.dumps(settings_payload(capture.settings), sort_keys=True)),
    }


def _concat(arrays, dtype, empty_shape):
    return np.concatenate(arrays).astype(dtype, copy=False) if arrays else np.empty(empty_shape, dtype=dtype)


def read_capture(path):
    with np.load(path, allow_pickle=False) as data:
        _check_protocol(data)
        sources = _read_sources(data)
        return SkinCapture(
            root_name=str(data["root_name"]),
            sources=tuple(sources),
            lower=data["lower"].astype(np.float64),
            upper=data["upper"].astype(np.float64),
            input_hash=str(data["input_hash"]),
            voxel_size=float(data["voxel_size"][0]),
            resolution=int(data["resolution"][0]),
            warnings=tuple(json.loads(str(data["warnings"]))),
            settings=settings_from_payload(json.loads(str(data["settings"]))),
        )


def _check_protocol(data):
    version = int(data["protocol_version"][0])
    if version != PROTOCOL_VERSION:
        raise ValueError(f"Unsupported draft-skin protocol {version}.")


def _read_sources(data):
    metadata = json.loads(str(data["metadata"]))
    voff, toff = data["vertex_offsets"], data["triangle_offsets"]
    for index, item in enumerate(metadata):
        yield SkinSource(
            **item,
            vertices=data["vertices"][voff[index] : voff[index + 1]].copy(),
            triangles=data["triangles"][toff[index] : toff[index + 1]].copy(),
            collagen=data["collagen"][voff[index] : voff[index + 1]].copy(),
        )


def write_result(path, result):
    report = {} if result.validation is None else asdict(result.validation)
    payload = {
        "protocol_version": np.asarray([PROTOCOL_VERSION], dtype=np.int32),
        "vertices": np.asarray(result.vertices, dtype=np.float32),
        "triangles": np.asarray(result.triangles, dtype=np.int32),
        "collagen": np.asarray(result.collagen, dtype=np.float32),
        "statistics": np.asarray(json.dumps(result.statistics)),
        "validation": np.asarray(json.dumps(report)),
    }
    payload.update(_binding_payload(result.binding, len(result.vertices)))
    atomic_npz(path, **payload)


def _binding_payload(binding, count):
    if binding is None:
        binding = _empty_binding(count)
    return {"bind_sources": np.asarray(binding.source_indices, dtype=np.int32),
            "bind_triangles": np.asarray(binding.triangle_indices, dtype=np.int32),
            "bind_barycentric": np.asarray(binding.barycentric, dtype=np.float32),
            "bind_weights": np.asarray(binding.weights, dtype=np.float32),
            "bind_normal_offset": np.asarray(binding.normal_offsets, dtype=np.float32),
            "bind_support": np.asarray(binding.support, dtype=np.float32),
            "bind_schema": np.asarray([binding.schema], dtype=np.int32)}


def _empty_binding(count):
    shape = (int(count), 4)
    return SkinWarmBinding(np.full(shape, -1), np.full(shape, -1),
                           np.zeros((*shape, 3)), np.zeros(shape),
                           np.zeros(count), np.zeros(count), 1)


def read_result(path):
    with np.load(path, allow_pickle=False) as data:
        _check_protocol(data)
        report = SkinValidationReport(**json.loads(str(data["validation"])))
        binding = _read_binding(data)
        return SkinResult(
            vertices=data["vertices"].copy(),
            triangles=data["triangles"].copy(),
            collagen=data["collagen"].copy(),
            statistics=json.loads(str(data["statistics"])),
            validation=report,
            binding=binding,
        )


def _read_binding(data):
    return SkinWarmBinding(data["bind_sources"].copy(), data["bind_triangles"].copy(),
                           data["bind_barycentric"].copy(), data["bind_weights"].copy(),
                           data["bind_normal_offset"].copy(), data["bind_support"].copy(),
                           int(data["bind_schema"][0]))


def capture_hash(root_name, sources, settings=DEFAULT_SETTINGS):
    digest = hashlib.sha256(str(root_name).encode("utf-8"))
    digest.update(json.dumps(settings_payload(settings), sort_keys=True).encode("utf-8"))
    for source in sources:
        _update_source_hash(digest, source)
    return digest.hexdigest()


def _update_source_hash(digest, source):
    digest.update(json.dumps(_source_metadata(source), sort_keys=True).encode("utf-8"))
    digest.update(np.ascontiguousarray(source.vertices).view(np.uint8))
    digest.update(np.ascontiguousarray(source.triangles).view(np.uint8))
    digest.update(np.ascontiguousarray(_source_collagen(source, len(source.vertices))).view(np.uint8))
