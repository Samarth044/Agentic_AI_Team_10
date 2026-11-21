"""Portal MCP server (course concept: MCP connector).

File, SQLite and API tools exposed through ONE MCP server over stdio. The
portal's agents reach every tool through this server (see portal/mcp_client.py).
External MCP clients can use it too:

  Run:      python mcp-server/portal_mcp_server.py
  Inspect:  npx @modelcontextprotocol/inspector python mcp-server/portal_mcp_server.py

SQLite access is read-only; file access is sandboxed to data/docs and data/resumes.
The portal process writes the audit log for each call, so this server stays silent
(stdout carries only MCP JSON-RPC frames)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from portal import connector  # noqa: E402

import logging  # noqa: E402

logging.getLogger("httpx").setLevel(logging.WARNING)
mcp = FastMCP("internship-portal", log_level="WARNING")

for _name, (_fn, _desc, _category, _props, _req) in connector.TOOLS.items():
    mcp.add_tool(_fn, name=_name, description=f"[{_category}] {_desc}")


if __name__ == "__main__":
    mcp.run()  # stdio transport
