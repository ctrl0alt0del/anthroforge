"""Checksummed, disposable native products; never a substitute for packed reference data."""
import hashlib
import json
import os
from pathlib import Path
import shutil


def directory():
    base = Path(os.environ.get("LOCALAPPDATA",str(Path.home()/".cache")))
    path = base/"AnthroForge/deformation/native-v1"; path.mkdir(parents=True,exist_ok=True)
    return path


def restore(folder):
    for meta in directory().glob("bbw_v1_*.json"):
        try:
            source = meta.with_suffix(".bin"); expected = json.loads(meta.read_text())["sha256"]
            if hashlib.sha256(source.read_bytes()).hexdigest() != expected: continue
            target = Path(folder)/source.name
            if not target.exists(): shutil.copyfile(source,target)
        except (OSError,ValueError,KeyError): continue


def retain(folder):
    for source in Path(folder).glob("bbw_v1_*.bin"):
        target = directory()/source.name; data = source.read_bytes()
        temporary = target.with_suffix(f".{os.getpid()}.tmp"); temporary.write_bytes(data); os.replace(temporary,target)
        target.with_suffix(".json").write_text(json.dumps(dict(sha256=hashlib.sha256(data).hexdigest())))
