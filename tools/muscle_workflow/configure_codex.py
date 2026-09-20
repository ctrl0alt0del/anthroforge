"""Set only this installed server's options, preserving unrelated Codex settings."""

import json
import os
import tomllib
from pathlib import Path

READ_TOOLS = ["chroma_list_collections", "chroma_get_collection_info",
              "chroma_get_collection_count", "chroma_get_documents",
              "chroma_query_documents", "chroma_peek_collection"]
HEADER = "[mcp_servers.anthroforge_chroma]"


def configure():
    path = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml"
    original = path.read_text(encoding="utf-8")
    parsed = tomllib.loads(original)
    server = parsed["mcp_servers"]["anthroforge_chroma"]
    desired = {"startup_timeout_sec": 45, "tool_timeout_sec": 60, "enabled_tools": READ_TOOLS}
    additions = [f"{key} = {json.dumps(value)}" for key, value in desired.items() if key not in server]
    updated = original.replace(HEADER, HEADER + "\n" + "\n".join(additions), 1)
    expected = dict(server, **{k: v for k, v in desired.items() if k not in server})
    assert tomllib.loads(updated)["mcp_servers"]["anthroforge_chroma"] == expected
    if additions:
        path.write_text(updated, encoding="utf-8")
    return {"configured": "anthroforge_chroma", "added_options": len(additions)}


if __name__ == "__main__":
    print(json.dumps(configure()))
