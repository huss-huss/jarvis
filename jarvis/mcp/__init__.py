"""MCP bridge stub — disabled by default (Phase 8 optional)."""

from __future__ import annotations


def mcp_status(*, enabled: bool) -> str:
    if not enabled:
        return (
            "MCP integrations are disabled (proactive.mcp_enabled: false). "
            "JARVIS core stays local and offline-capable."
        )
    return (
        "MCP is marked enabled in config, but no connectors are bundled yet. "
        "Skills/MCP adapters can be added later without changing the permission model."
    )


def list_mcp_tools(*, enabled: bool) -> list[str]:
    if not enabled:
        return []
    return []
