"""Exercise official MCP discovery and semantic retrieval in fresh sessions."""

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from common import COLLECTION, environment, now, root, write_json


def parameters():
    return StdioServerParameters(command=sys.executable, env=environment(),
        args=[str(Path(__file__).with_name("mcp_server.py"))])


async def inspect(session):
    await session.initialize()
    names = [tool.name for tool in (await session.list_tools()).tools]
    assert "chroma_query_documents" in names
    result = await session.call_tool("chroma_query_documents", {
        "collection_name": COLLECTION, "query_texts": ["Preserve belly width and boundaries in the actual native loft"],
        "n_results": 1, "where": {"id": "native-base-width-before-depth"}})
    assert not result.isError, result
    content = "\n".join(item.text for item in result.content if hasattr(item, "text"))
    assert "native-base-width-before-depth" in content, content
    return {"tool_count": len(names), "indexed_procedure_found": True, "result": content}


async def session_check():
    async with stdio_client(parameters()) as streams:
        async with ClientSession(*streams) as session:
            return await inspect(session)


async def main():
    first = await session_check()
    concurrent = await asyncio.gather(session_check(), session_check())
    result = {"checked_at": now(), "first_session": first, "fresh_concurrent_sessions": concurrent}
    path = write_json(root() / "checks" / "mcp.json", result)
    print(json.dumps({"passed": True, "sessions": 3, "report": str(path)}))


if __name__ == "__main__":
    asyncio.run(main())
