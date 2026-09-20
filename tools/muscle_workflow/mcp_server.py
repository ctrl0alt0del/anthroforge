"""Launch official Chroma MCP after ensuring the shared local service exists."""

import contextlib
import sys

from service import client


def main():
    with contextlib.redirect_stdout(sys.stderr):
        connection = client()
        from chroma_mcp import server
        server._chroma_client = connection
    server.mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
