"""The MCP server: what AI agents connect to at `/mcp` (streamable HTTP, bearer tokens).

`create_mcp_server` builds the SDK's `MCPServer`, `mcp_asgi_app` the ASGI app that
`todolist.app.create_app` routes `/mcp` to. Tools live in `tools.py`.
"""

from todolist.mcp_server.server import create_mcp_server, mcp_asgi_app

__all__ = ["create_mcp_server", "mcp_asgi_app"]
