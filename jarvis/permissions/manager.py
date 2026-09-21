"""Permission manager — LLM cannot bypass these checks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from jarvis.config import PermissionsConfig
from jarvis.logging import get_logger
from jarvis.tools.base import PermissionLevel, Tool

log = get_logger(__name__)

ConfirmCallback = Callable[[str], bool]


@dataclass
class PermissionDecision:
    allowed: bool
    confirmed: bool
    reason: str


class PermissionManager:
    def __init__(
        self,
        config: PermissionsConfig,
        confirm: ConfirmCallback | None = None,
        *,
        voice_style: bool = False,
    ) -> None:
        self.config = config
        self._confirm = confirm or (lambda _prompt: False)
        self.voice_style = voice_style

    def authorize(self, tool: Tool, arguments: dict[str, Any] | None = None) -> PermissionDecision:
        level = tool.permission
        args = arguments or {}
        summary = f"{tool.name}({_format_args(args)})"

        if level is PermissionLevel.SAFE:
            log.info("permission_allow", tool=tool.name, level=level.value, confirmed=False)
            return PermissionDecision(allowed=True, confirmed=False, reason="safe")

        if level is PermissionLevel.MODIFICATION:
            if self.config.modification_actions == "allow":
                log.info("permission_allow", tool=tool.name, level=level.value, confirmed=False)
                return PermissionDecision(allowed=True, confirmed=False, reason="modification_auto")
            prompt = self._modification_prompt(summary)
            ok = self._confirm(prompt)
            log.info("permission_decision", tool=tool.name, level=level.value, allowed=ok, confirmed=True)
            return PermissionDecision(
                allowed=ok,
                confirmed=True,
                reason="modification_confirmed" if ok else "modification_denied",
            )

        # DANGEROUS — always confirm; never auto-allow (LLM cannot bypass)
        prompt = self._dangerous_prompt(tool.name, summary)
        ok = self._confirm(prompt)
        log.info("permission_decision", tool=tool.name, level=level.value, allowed=ok, confirmed=True)
        return PermissionDecision(
            allowed=ok,
            confirmed=True,
            reason="dangerous_confirmed" if ok else "dangerous_denied",
        )

    def _modification_prompt(self, summary: str) -> str:
        if self.voice_style:
            return (
                f"I am about to make a change: {summary}. "
                "Are you sure? Please say yes or no."
            )
        return f"Allow modification action `{summary}`? [y/N] "

    def _dangerous_prompt(self, tool_name: str, summary: str) -> str:
        if self.voice_style:
            action = tool_name.replace("_", " ")
            return (
                f"This is a dangerous action. I really want to {action}. "
                f"Details: {summary}. Are you sure you want me to do this? "
                "Please say yes or no."
            )
        return f"DANGEROUS action requested: `{summary}`. Confirm? [y/N] "


def _format_args(args: dict[str, Any]) -> str:
    parts = []
    for key, value in args.items():
        text = repr(value)
        if len(text) > 80:
            text = text[:77] + "..."
        parts.append(f"{key}={text}")
    return ", ".join(parts)
