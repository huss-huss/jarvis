"""Phase 5 browser tools with a fake provider."""

from __future__ import annotations

from jarvis.browser.base import BrowserProvider, PageSnapshot
from jarvis.tools.browser import build_browser_tools
from jarvis.tools.registry import ToolRegistry


class _FakeBrowser(BrowserProvider):
    def __init__(self) -> None:
        self.url = "about:blank"
        self.title = "Blank"
        self.text = ""
        self.closed = False

    def open(self, url: str = "about:blank") -> PageSnapshot:
        return self.navigate(url)

    def navigate(self, url: str) -> PageSnapshot:
        self.url = url if url.startswith("http") else f"https://{url}"
        self.title = "Example"
        self.text = f"Hello from {self.url}"
        return self.get_text()

    def get_text(self, *, max_chars: int = 12_000) -> PageSnapshot:
        return PageSnapshot(url=self.url, title=self.title, text=self.text[:max_chars])

    def click(self, selector: str) -> PageSnapshot:
        self.text = f"clicked:{selector}"
        return self.get_text()

    def type_text(self, selector: str, text: str, *, submit: bool = False) -> PageSnapshot:
        self.text = f"typed:{text} into {selector} submit={submit}"
        return self.get_text()

    def close(self) -> None:
        self.closed = True


def test_browser_tools_with_fake_provider():
    browser = _FakeBrowser()
    registry = ToolRegistry()
    for tool in build_browser_tools(browser):
        registry.register(tool)

    opened = registry.execute("open_browser", {"url": "example.com"})
    assert opened.success
    assert "example.com" in opened.output

    text = registry.execute("get_page_text", {})
    assert text.success
    assert "Hello" in text.output

    clicked = registry.execute("click_browser", {"selector": "#go"})
    assert clicked.success
    assert "clicked:#go" in clicked.output

    typed = registry.execute("type_browser", {"selector": "input", "text": "hi", "submit": True})
    assert typed.success
    assert "typed:hi" in typed.output

    closed = registry.execute("close_browser", {})
    assert closed.success
    assert browser.closed is True
