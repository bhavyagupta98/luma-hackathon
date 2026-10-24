from __future__ import annotations

from typing import Any, Protocol

from mcp import Client

from .config import backend_mcp_url


class BackendClient(Protocol):
    async def call(self, tool: str, **arguments: Any) -> dict[str, Any]: ...


class McpBackendClient:
    def __init__(self, url: str | None = None) -> None:
        self.url = url or backend_mcp_url()

    async def call(self, tool: str, **arguments: Any) -> dict[str, Any]:
        async with Client(self.url) as client:
            response = await client.call_tool(tool, arguments)
        return dict(response.structured_content or {})


def make_backend_client() -> BackendClient:
    return McpBackendClient()
