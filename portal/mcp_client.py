"""MCP client (course concept: MCP connector).

The portal starts its own MCP server (mcp-server/portal_mcp_server.py) as a
child process and talks to it over stdio using the official MCP Python SDK.
Every agent tool call (files, SQLite, APIs) goes through this one
connection: `initialize` -> `tools/list` -> `tools/call`.

The session lives on a dedicated asyncio loop thread so the synchronous
FastAPI handlers and agents can call it safely."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading

from .config import ROOT

SERVER = ROOT / "mcp-server" / "portal_mcp_server.py"


class Unavailable(Exception):
    """The MCP server could not be started or reached."""


class ToolError(Exception):
    """The tool ran and reported an error."""


class MCPClient:
    def __init__(self):
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._session = None
        self._ready = threading.Event()
        self.server_info: dict = {}
        self.tools: list[dict] = []
        self.error = ""

    # ------------------------------------------------------------ lifecycle
    async def _serve(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        params = StdioServerParameters(command=sys.executable, args=[str(SERVER)],
                                       env={**os.environ, "PYTHONIOENCODING": "utf-8"}, cwd=str(ROOT))
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    self.server_info = {"name": init.serverInfo.name, "version": init.serverInfo.version,
                                        "protocol": init.protocolVersion, "transport": "stdio",
                                        "command": f"python {SERVER.relative_to(ROOT)}"}
                    listed = await session.list_tools()
                    self.tools = [{"name": t.name, "description": t.description,
                                   "input_schema": t.inputSchema} for t in listed.tools]
                    self._session = session
                    self._ready.set()
                    await asyncio.Event().wait()  # keep the session open for the app's lifetime
        except Exception as e:  # noqa: BLE001
            self.error = f"{type(e).__name__}: {e}"[:300]
            self._session = None
            self._ready.set()

    def _ensure(self):
        if self._session:
            return
        with self._lock:
            if self._session:
                return
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                threading.Thread(target=self._loop.run_forever, daemon=True, name="mcp-client").start()
            self._ready.clear()
            self.error = ""
            asyncio.run_coroutine_threadsafe(self._serve(), self._loop)
            if not self._ready.wait(30) or not self._session:
                raise Unavailable(self.error or "MCP server did not start within 30s")

    # ------------------------------------------------------------ calls
    def call(self, tool: str, args: dict) -> dict:
        self._ensure()
        fut = asyncio.run_coroutine_threadsafe(self._session.call_tool(tool, args), self._loop)
        try:
            res = fut.result(90)
        except Exception as e:  # noqa: BLE001  transport broke: reconnect next time
            self._session = None
            raise Unavailable(str(e)[:200])
        text = "".join(getattr(c, "text", "") for c in res.content)
        if res.isError:
            raise ToolError(text or "tool failed")
        data = res.structuredContent
        if data is None:
            data = json.loads(text) if text else {}
        if isinstance(data, dict) and set(data) == {"result"}:
            data = data["result"]
        return data

    def status(self) -> dict:
        try:
            self._ensure()
        except Unavailable:
            pass
        return {"connected": bool(self._session), "server": self.server_info, "tools": self.tools,
                "error": self.error}


client = MCPClient()
