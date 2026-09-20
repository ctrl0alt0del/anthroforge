"""Artifact paths and reproducible file references; independent of Blender."""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

DEFAULT_ROOT = "E:/development/WIP_models/muscle_reconstruction_workflow"
STAGES = ("transfer", "base", "fibers", "inflation", "review")
COLLECTION = "anthroforge_muscle_lessons"


def root():
    return Path(os.environ.get("AF_MUSCLE_WORKFLOW_HOME", DEFAULT_ROOT)).resolve()


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)
    return path


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def reference(path, claim=None):
    path = Path(path).resolve(strict=True)
    result = {"path": path.as_posix(), "sha256": digest(path)}
    if claim is not None:
        result["claim"] = claim
    return result


def verify_reference(item):
    if digest(item["path"]) != item["sha256"]:
        raise ValueError("Artifact changed: " + item["path"])


def environment():
    result = dict(os.environ)
    result.update(ANONYMIZED_TELEMETRY="False", CHROMA_OTEL_COLLECTION_ENDPOINT="")
    result["AF_MUSCLE_WORKFLOW_HOME"] = root().as_posix()
    return result


def configure_embeddings():
    os.environ["ANONYMIZED_TELEMETRY"] = "False"
    from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2
    ONNXMiniLM_L6_V2.DOWNLOAD_PATH = root() / "runtime" / "embeddings" / "all-MiniLM-L6-v2"


def settings():
    return read_json(root() / "settings.json")
