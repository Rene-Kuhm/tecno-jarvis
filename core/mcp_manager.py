from __future__ import annotations

import asyncio
import json
import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from core.config import BASE_DIR


MCP_CONFIG_PATH = BASE_DIR / "config" / "mcp_servers.json"
MCP_LOCAL_CONFIG_PATH = BASE_DIR / "config" / "mcp_servers.local.json"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _merge_servers(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    servers = dict(base.get("servers") or {})
    for name, cfg in (override.get("servers") or {}).items():
        current = dict(servers.get(name) or {})
        current.update(cfg or {})
        servers[name] = current
    merged["servers"] = servers
    return merged


def load_mcp_config() -> dict[str, Any]:
    cfg = _load_json(MCP_CONFIG_PATH)
    local_cfg = _load_json(MCP_LOCAL_CONFIG_PATH)
    if local_cfg:
        cfg = _merge_servers(cfg, local_cfg)
    return cfg


def _resolve_env(env_cfg: dict[str, str] | None) -> dict[str, str]:
    env = dict(os.environ)
    for key, value in (env_cfg or {}).items():
        if isinstance(value, str) and value.startswith("$"):
            resolved = os.environ.get(value[1:], "")
            if resolved:
                env[key] = resolved
        elif value not in (None, ""):
            env[key] = str(value)
    return env


def _resolve_arg(value: Any) -> str:
    text = str(value).replace("{BASE_DIR}", str(BASE_DIR))
    return os.path.expandvars(os.path.expanduser(text))


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(val) for key, val in value.items()}
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump())
    if hasattr(value, "dict"):
        return _json_safe(value.dict())
    return str(value)


class MCPServerSession:
    def __init__(self, name: str, cfg: dict[str, Any]):
        self.name = name
        self.cfg = cfg
        self._stack: AsyncExitStack | None = None
        self._session = None
        self._lock = asyncio.Lock()

    async def ensure_started(self):
        async with self._lock:
            if self._session is not None:
                return self._session

            try:
                from mcp import ClientSession, StdioServerParameters
                from mcp.client.stdio import stdio_client
            except Exception as exc:
                raise RuntimeError(
                    "Python package 'mcp' is not installed. Run install.bat or pip install -r requirements.txt."
                ) from exc

            command = self.cfg.get("command")
            if not command:
                raise RuntimeError(f"MCP server '{self.name}' has no command configured.")

            params = StdioServerParameters(
                command=_resolve_arg(command),
                args=[_resolve_arg(arg) for arg in self.cfg.get("args", [])],
                env=_resolve_env(self.cfg.get("env")),
            )

            stack = AsyncExitStack()
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()

            self._stack = stack
            self._session = session
            return session

    async def list_tools(self) -> list[dict[str, Any]]:
        session = await self.ensure_started()
        result = await session.list_tools()
        tools = []
        for tool in result.tools:
            tools.append({
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": _json_safe(getattr(tool, "inputSchema", None)),
            })
        return tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        session = await self.ensure_started()
        result = await session.call_tool(tool_name, arguments=arguments)
        return _json_safe(result)

    async def close(self) -> None:
        stack = self._stack
        self._stack = None
        self._session = None
        if stack is None:
            return
        try:
            await stack.aclose()
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise


class MCPManager:
    def __init__(self):
        self._sessions: dict[str, MCPServerSession] = {}

    def _server_configs(self) -> dict[str, dict[str, Any]]:
        cfg = load_mcp_config()
        servers = cfg.get("servers") or {}
        return {name: server for name, server in servers.items() if isinstance(server, dict)}

    def available_servers(self) -> dict[str, dict[str, Any]]:
        return {
            name: cfg
            for name, cfg in self._server_configs().items()
            if bool(cfg.get("enabled", False))
        }

    def _get_session(self, server_name: str) -> MCPServerSession:
        servers = self.available_servers()
        if server_name not in servers:
            enabled = ", ".join(sorted(servers)) or "none"
            raise RuntimeError(f"MCP server '{server_name}' is not enabled. Enabled servers: {enabled}.")
        if server_name not in self._sessions:
            self._sessions[server_name] = MCPServerSession(server_name, servers[server_name])
        return self._sessions[server_name]

    async def list_tools(self, server_name: str | None = None) -> dict[str, Any]:
        servers = self.available_servers()
        if server_name:
            servers = {server_name: servers[server_name]} if server_name in servers else {}

        output: dict[str, Any] = {}
        for name in sorted(servers):
            cfg = servers[name]
            try:
                output[name] = {
                    "description": cfg.get("description", ""),
                    "category": cfg.get("category", "utility"),
                    "risk": cfg.get("risk", "medium"),
                    "tools": await self._get_session(name).list_tools(),
                }
            except Exception as exc:
                output[name] = {"error": str(exc)}
        return output

    async def list_tools_text(self, server_name: str | None = None) -> str:
        data = await self.list_tools(server_name)
        return json.dumps(data, ensure_ascii=False, indent=2)[:12000]

    async def call_tool_text(self, server_name: str, tool_name: str, arguments_json: str | None = None) -> str:
        arguments: dict[str, Any] = {}
        if arguments_json:
            try:
                parsed = json.loads(arguments_json)
                if isinstance(parsed, dict):
                    arguments = parsed
                else:
                    raise ValueError("arguments_json must decode to an object")
            except Exception as exc:
                raise RuntimeError(f"Invalid arguments_json: {exc}") from exc

        result = await self._get_session(server_name).call_tool(tool_name, arguments)
        return json.dumps(result, ensure_ascii=False, indent=2)[:12000]

    async def close_all(self) -> None:
        for session in list(self._sessions.values()):
            await session.close()
        self._sessions.clear()


_manager = MCPManager()


def get_mcp_manager() -> MCPManager:
    return _manager
