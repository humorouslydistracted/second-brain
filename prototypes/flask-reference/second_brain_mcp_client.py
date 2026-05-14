from __future__ import annotations

import asyncio
import atexit
import os
import socket
import subprocess
import sys
import threading
import time
from typing import Any

from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client

from second_brain_core import APP_DIR

SERVER_SCRIPT = os.path.join(APP_DIR, "second_brain_mcp_server.py")
SERVER_HOST = os.environ.get("SECOND_BRAIN_MCP_HOST", "127.0.0.1")
SERVER_PORT = int(os.environ.get("SECOND_BRAIN_MCP_PORT", "8765"))
SERVER_URL = os.environ.get(
    "SECOND_BRAIN_MCP_URL",
    f"http://{SERVER_HOST}:{SERVER_PORT}/mcp",
)
AUTOSTART = os.environ.get("SECOND_BRAIN_MCP_AUTOSTART", "1").lower() not in {
    "0",
    "false",
    "no",
}
SERVER_LOG_PATH = os.path.join(APP_DIR, "second_brain_mcp_server.log")

_server_process: subprocess.Popen[str] | None = None
_server_log_handle = None
_server_lock = threading.Lock()


def _flatten_tool_result(result: types.CallToolResult) -> dict[str, Any]:
    payload = {}
    if getattr(result, "structuredContent", None):
        payload = dict(result.structuredContent)

    text_parts = []
    for content in result.content:
        if isinstance(content, types.TextContent):
            text_parts.append(content.text)

    if text_parts and "response_text" not in payload:
        payload["response_text"] = "\n".join(text_parts)

    if result.isError:
        payload["is_error"] = True

    return payload


def _server_is_listening(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


def _read_server_log_tail(max_chars: int = 1200) -> str:
    if not os.path.exists(SERVER_LOG_PATH):
        return ""
    with open(SERVER_LOG_PATH, "r", encoding="utf-8", errors="replace") as handle:
        data = handle.read()
    return data[-max_chars:]


def _terminate_server_process() -> None:
    global _server_log_handle, _server_process
    if _server_process and _server_process.poll() is None:
        _server_process.terminate()
        try:
            _server_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _server_process.kill()
    _server_process = None
    if _server_log_handle:
        _server_log_handle.close()
        _server_log_handle = None


def ensure_server_running(timeout_seconds: float = 12.0) -> None:
    global _server_log_handle, _server_process
    if _server_is_listening(SERVER_HOST, SERVER_PORT):
        return

    if not AUTOSTART:
        raise RuntimeError(f"MCP server is not running at {SERVER_URL}")

    with _server_lock:
        if _server_is_listening(SERVER_HOST, SERVER_PORT):
            return

        if _server_process and _server_process.poll() is not None:
            _server_process = None

        if _server_process is None:
            env = os.environ.copy()
            env["SECOND_BRAIN_MCP_TRANSPORT"] = "streamable-http"
            env["SECOND_BRAIN_MCP_HOST"] = SERVER_HOST
            env["SECOND_BRAIN_MCP_PORT"] = str(SERVER_PORT)
            _server_log_handle = open(SERVER_LOG_PATH, "a", encoding="utf-8")
            _server_process = subprocess.Popen(
                [sys.executable, SERVER_SCRIPT, "streamable-http"],
                cwd=APP_DIR,
                env=env,
                stdout=_server_log_handle,
                stderr=subprocess.STDOUT,
                text=True,
            )

        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if _server_is_listening(SERVER_HOST, SERVER_PORT):
                return
            if _server_process and _server_process.poll() is not None:
                tail = _read_server_log_tail()
                raise RuntimeError(
                    "MCP server exited during startup."
                    + (f"\n{tail}" if tail else "")
                )
            time.sleep(0.2)

        raise RuntimeError(f"MCP server did not start within {timeout_seconds:.1f}s")


atexit.register(_terminate_server_process)


async def _call_tool_async(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = await session.call_tool(name, arguments=arguments or {})
    return _flatten_tool_result(result)


async def process_text_async(text: str) -> dict[str, Any]:
    ensure_server_running()
    async with streamable_http_client(SERVER_URL) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await _call_tool_async(session, "handle_input", {"text": text})
            return {
                "kind": result.get("kind", "unknown"),
                "response_text": result.get("response_text", "No response"),
                "result": result,
            }


def process_text_sync(text: str) -> dict[str, Any]:
    return asyncio.run(process_text_async(text))


async def call_tool_async(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    ensure_server_running()
    async with streamable_http_client(SERVER_URL) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await _call_tool_async(session, name, arguments)


def call_tool_sync(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    return asyncio.run(call_tool_async(name, arguments))
