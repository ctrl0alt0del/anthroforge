"""One loopback Chroma service shared by concurrent MCP and CLI clients."""

import json
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

from filelock import FileLock

from common import configure_embeddings, environment, now, root, settings, write_json


def heartbeat():
    address = f"http://127.0.0.1:{settings()['port']}/api/v2/heartbeat"
    try:
        with urlopen(address, timeout=1) as response:
            return "nanosecond heartbeat" in json.load(response)
    except (OSError, URLError, ValueError):
        return False


def spawn_server():
    executable = root() / "runtime" / ".venv" / "Scripts" / "chroma.exe"
    args = [str(executable), "run", "--path", str(root() / "knowledge" / "chroma")]
    args += ["--host", "127.0.0.1", "--port", str(settings()["port"])]
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    with (root() / "logs" / "chroma-server.log").open("ab") as log:
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   cwd=root(), env=environment(), creationflags=flags)
    write_json(root() / "runtime" / "server.json", {"pid": process.pid, "started": now()})
    return process


def wait_ready(process):
    for _ in range(100):
        if heartbeat():
            return
        if process.poll() is not None:
            raise RuntimeError("Chroma exited; inspect logs/chroma-server.log")
        time.sleep(0.2)
    raise TimeoutError("Chroma did not start; inspect logs/chroma-server.log")


def ensure_server():
    with FileLock(str(root() / "runtime" / "startup.lock"), timeout=40):
        if heartbeat():
            if not (root() / "runtime" / "server.json").exists():
                raise RuntimeError("Port is occupied by an unowned Chroma service")
        else:
            wait_ready(spawn_server())


def client():
    configure_embeddings()
    ensure_server()
    import chromadb
    from chromadb.config import Settings
    result = chromadb.HttpClient(host="127.0.0.1", port=settings()["port"],
                                settings=Settings(anonymized_telemetry=False))
    identity = result.get_or_create_collection("anthroforge_workflow_identity",
                                               metadata={"root": root().as_posix()})
    if identity.metadata["root"] != root().as_posix():
        raise RuntimeError("Chroma belongs to a different artifact directory")
    return result
