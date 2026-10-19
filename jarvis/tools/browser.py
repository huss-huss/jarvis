"""Browser tools backed by BrowserProvider."""

from __future__ import annotations

from typing import Any

from jarvis.browser.base import BrowserProvider, PageSnapshot
from jarvis.tools.base import PermissionLevel, Tool, ToolResult


def _format_snap(snap: PageSnapshot) -> str:
    body = snap.text or "(empty page text)"
    return f"URL: {snap.url}\nTitle: {snap.title}\n\n{body}"


class _BrowserTool(Tool):
    def __init__(self, browser: BrowserProvider) -> None:
        self.browser = browser


class OpenBrowserTool(_BrowserTool):
    name = "open_browser"
    description = "Open a browser page (Playwright). Pass a URL or leave blank for about:blank."
    permission = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to open (http/https)."},
        },
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        try:
            snap = self.browser.open(str(kwargs.get("url") or "about:blank"))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, output="", error=str(exc))
        return ToolResult(success=True, output=_format_snap(snap))


class NavigateBrowserTool(_BrowserTool):
    name = "navigate_browser"
    description = "Navigate the open browser to a URL."
    permission = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
        },
        "required": ["url"],
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        url = str(kwargs.get("url") or "").strip()
        if not url:
            return ToolResult(success=False, output="", error="url is required")
        try:
            snap = self.browser.navigate(url)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, output="", error=str(exc))
        return ToolResult(success=True, output=_format_snap(snap))


class GetPageTextTool(_BrowserTool):
    name = "get_page_text"
    description = "Read visible text from the current browser page."
    permission = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "max_chars": {"type": "integer"},
        },
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        max_chars = int(kwargs.get("max_chars") or 12_000)
        try:
            snap = self.browser.get_text(max_chars=max(1000, min(max_chars, 50_000)))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, output="", error=str(exc))
        return ToolResult(success=True, output=_format_snap(snap))


class ClickBrowserTool(_BrowserTool):
    name = "click_browser"
    description = "Click an element on the page using a CSS selector."
    permission = PermissionLevel.MODIFICATION
    parameters = {
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "CSS selector."},
        },
        "required": ["selector"],
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        selector = str(kwargs.get("selector") or "").strip()
        if not selector:
            return ToolResult(success=False, output="", error="selector is required")
        try:
            snap = self.browser.click(selector)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, output="", error=str(exc))
        return ToolResult(success=True, output=_format_snap(snap))


class TypeBrowserTool(_BrowserTool):
    name = "type_browser"
    description = "Type text into an input matching a CSS selector. Optionally press Enter."
    permission = PermissionLevel.MODIFICATION
    parameters = {
        "type": "object",
        "properties": {
            "selector": {"type": "string"},
            "text": {"type": "string"},
            "submit": {"type": "boolean"},
        },
        "required": ["selector", "text"],
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        selector = str(kwargs.get("selector") or "").strip()
        text = str(kwargs.get("text") or "")
        submit = bool(kwargs.get("submit", False))
        if not selector:
            return ToolResult(success=False, output="", error="selector is required")
        try:
            snap = self.browser.type_text(selector, text, submit=submit)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, output="", error=str(exc))
        return ToolResult(success=True, output=_format_snap(snap))


class CloseBrowserTool(_BrowserTool):
    name = "close_browser"
    description = "Close the browser session."
    permission = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    def execute(self, **kwargs: Any) -> ToolResult:
        try:
            self.browser.close()
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, output="", error=str(exc))
        return ToolResult(success=True, output="Browser closed.")


def build_browser_tools(browser: BrowserProvider) -> list[Tool]:
    return [
        OpenBrowserTool(browser),
        NavigateBrowserTool(browser),
        GetPageTextTool(browser),
        ClickBrowserTool(browser),
        TypeBrowserTool(browser),
        CloseBrowserTool(browser),
    ]
