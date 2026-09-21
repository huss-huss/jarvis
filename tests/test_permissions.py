"""Permission manager tests — dangerous actions cannot be bypassed."""

from jarvis.config import PermissionsConfig
from jarvis.permissions.manager import PermissionManager
from jarvis.tools.base import PermissionLevel, Tool, ToolResult


class _SafeTool(Tool):
    name = "safe_tool"
    description = "safe"
    permission = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    def execute(self, **kwargs):
        return ToolResult(success=True, output="ok")


class _ModTool(Tool):
    name = "mod_tool"
    description = "mod"
    permission = PermissionLevel.MODIFICATION
    parameters = {"type": "object", "properties": {}}

    def execute(self, **kwargs):
        return ToolResult(success=True, output="ok")


class _DangerTool(Tool):
    name = "danger_tool"
    description = "danger"
    permission = PermissionLevel.DANGEROUS
    parameters = {"type": "object", "properties": {}}

    def execute(self, **kwargs):
        return ToolResult(success=True, output="should not auto-run")


def test_safe_allows_without_confirm():
    calls: list[str] = []
    mgr = PermissionManager(PermissionsConfig(), confirm=lambda p: calls.append(p) or True)
    decision = mgr.authorize(_SafeTool())
    assert decision.allowed is True
    assert decision.confirmed is False
    assert calls == []


def test_modification_requires_confirm_by_default():
    mgr = PermissionManager(PermissionsConfig(), confirm=lambda _p: False)
    decision = mgr.authorize(_ModTool())
    assert decision.allowed is False
    assert decision.confirmed is True


def test_modification_can_be_auto_allowed():
    cfg = PermissionsConfig(modification_actions="allow")
    mgr = PermissionManager(cfg, confirm=lambda _p: False)
    decision = mgr.authorize(_ModTool())
    assert decision.allowed is True
    assert decision.confirmed is False


def test_dangerous_always_requires_confirm_even_if_user_would_auto():
    """DANGEROUS must never be auto-allowed via config."""
    cfg = PermissionsConfig(modification_actions="allow")
    denied = PermissionManager(cfg, confirm=lambda _p: False).authorize(_DangerTool())
    assert denied.allowed is False
    assert denied.confirmed is True

    allowed = PermissionManager(cfg, confirm=lambda _p: True).authorize(_DangerTool())
    assert allowed.allowed is True
    assert allowed.confirmed is True
