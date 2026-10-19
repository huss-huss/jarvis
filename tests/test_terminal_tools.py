"""Phase 5 terminal allowlist / deny tests."""

from __future__ import annotations

from pathlib import Path

from jarvis.config import PermissionsConfig
from jarvis.permissions.manager import PermissionManager
from jarvis.tools.base import PermissionLevel
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.terminal import RunCommandTool, build_terminal_tools


def test_allowlisted_command_runs(tmp_path: Path):
    tool = RunCommandTool(cwd=tmp_path, timeout_seconds=10)
    result = tool.execute(command="pwd")
    assert result.success
    assert str(tmp_path) in result.output or result.output


def test_blocks_rm_and_shell_operators(tmp_path: Path):
    tool = RunCommandTool(cwd=tmp_path)
    assert tool.execute(command="rm -rf /").success is False
    assert tool.execute(command="echo hi; ls").success is False
    assert tool.execute(command="ls | wc").success is False
    assert tool.execute(command="sudo ls").success is False
    assert tool.execute(command="curl http://example.com").success is False  # not allowlisted


def test_git_force_blocked(tmp_path: Path):
    tool = RunCommandTool(cwd=tmp_path)
    bad = tool.execute(command="git reset --hard")
    assert bad.success is False
    assert "not allowed" in (bad.error or "").lower() or "blocked" in (bad.error or "").lower()


def test_destructive_command_is_dangerous_permission(tmp_path: Path):
    tool = RunCommandTool(cwd=tmp_path)
    assert tool.permission_for(command="ls") is PermissionLevel.MODIFICATION
    assert tool.permission_for(command="rm -rf tmp") is PermissionLevel.DANGEROUS


def test_permission_manager_uses_permission_for(tmp_path: Path):
    tool = RunCommandTool(cwd=tmp_path)
    denied: list[bool] = []

    def confirm(_prompt: str) -> bool:
        denied.append(True)
        return False

    pm = PermissionManager(PermissionsConfig(modification_actions="allow"), confirm=confirm)
    # destructive → DANGEROUS → confirm called → denied
    decision = pm.authorize(tool, {"command": "rm -rf x"})
    assert decision.allowed is False
    assert denied == [True]

    # safe allowlisted under modification_actions=allow → no confirm
    denied.clear()
    decision2 = pm.authorize(tool, {"command": "pwd"})
    assert decision2.allowed is True
    assert denied == []


def test_build_terminal_tools_registers(tmp_path: Path):
    registry = ToolRegistry()
    for tool in build_terminal_tools(cwd=tmp_path):
        registry.register(tool)
    assert registry.get("run_command") is not None
