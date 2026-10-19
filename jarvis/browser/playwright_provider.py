"""Playwright-backed browser provider (optional dependency)."""

from __future__ import annotations

from jarvis.browser.base import BrowserProvider, PageSnapshot
from jarvis.logging import get_logger

log = get_logger(__name__)


class PlaywrightBrowser(BrowserProvider):
    def __init__(self, *, headless: bool = True, timeout_ms: int = 30_000) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - exercised via UnavailableBrowser
            raise RuntimeError(
                "Playwright is not installed. Run: uv sync --extra browser && playwright install chromium"
            ) from exc

        self.headless = headless
        self.timeout_ms = timeout_ms
        self._pw_cm = sync_playwright()
        self._pw = self._pw_cm.__enter__()
        self._browser = self._pw.chromium.launch(headless=headless)
        self._context = self._browser.new_context()
        self._page = self._context.new_page()
        self._page.set_default_timeout(timeout_ms)

    def open(self, url: str = "about:blank") -> PageSnapshot:
        return self.navigate(url)

    def navigate(self, url: str) -> PageSnapshot:
        target = (url or "").strip() or "about:blank"
        if not target.startswith(("http://", "https://", "about:", "file://")):
            target = "https://" + target
        self._page.goto(target, wait_until="domcontentloaded")
        return self.get_text()

    def get_text(self, *, max_chars: int = 12_000) -> PageSnapshot:
        title = self._page.title()
        url = self._page.url
        text = self._page.inner_text("body") if self._page.query_selector("body") else ""
        text = (text or "").strip()
        if len(text) > max_chars:
            text = text[:max_chars] + "\n…[truncated]"
        return PageSnapshot(url=url, title=title, text=text)

    def click(self, selector: str) -> PageSnapshot:
        self._page.click(selector)
        self._page.wait_for_load_state("domcontentloaded")
        return self.get_text()

    def type_text(self, selector: str, text: str, *, submit: bool = False) -> PageSnapshot:
        self._page.fill(selector, text)
        if submit:
            self._page.press(selector, "Enter")
            self._page.wait_for_load_state("domcontentloaded")
        return self.get_text()

    def close(self) -> None:
        try:
            self._context.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._browser.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._pw_cm.__exit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass

    def health(self) -> tuple[bool, str]:
        return True, f"playwright chromium headless={self.headless}"


class UnavailableBrowser(BrowserProvider):
    def __init__(self, reason: str) -> None:
        self.reason = reason

    def open(self, url: str = "about:blank") -> PageSnapshot:
        raise RuntimeError(self.reason)

    def navigate(self, url: str) -> PageSnapshot:
        raise RuntimeError(self.reason)

    def get_text(self, *, max_chars: int = 12_000) -> PageSnapshot:
        raise RuntimeError(self.reason)

    def click(self, selector: str) -> PageSnapshot:
        raise RuntimeError(self.reason)

    def type_text(self, selector: str, text: str, *, submit: bool = False) -> PageSnapshot:
        raise RuntimeError(self.reason)

    def close(self) -> None:
        return None

    def health(self) -> tuple[bool, str]:
        return False, self.reason


def create_browser(*, headless: bool = True, enabled: bool = True) -> BrowserProvider:
    """Return a browser provider. Chromium starts on first use via SessionBrowser."""
    return SessionBrowser(headless=headless, enabled=enabled)


class SessionBrowser(BrowserProvider):
    """Lazy Playwright session — JARVIS still starts if browsers aren't installed."""

    def __init__(self, *, headless: bool = True, enabled: bool = True) -> None:
        self.headless = headless
        self.enabled = enabled
        self._inner: BrowserProvider | None = None

    def _ensure(self) -> BrowserProvider:
        if self._inner is None:
            if not self.enabled:
                self._inner = UnavailableBrowser(
                    "Browser tools disabled in config (browser.enabled: false)"
                )
            else:
                try:
                    self._inner = PlaywrightBrowser(headless=self.headless)
                except Exception as exc:  # noqa: BLE001
                    log.warning("playwright_unavailable", error=str(exc))
                    self._inner = UnavailableBrowser(str(exc))
        return self._inner

    def open(self, url: str = "about:blank") -> PageSnapshot:
        return self._ensure().open(url)

    def navigate(self, url: str) -> PageSnapshot:
        return self._ensure().navigate(url)

    def get_text(self, *, max_chars: int = 12_000) -> PageSnapshot:
        return self._ensure().get_text(max_chars=max_chars)

    def click(self, selector: str) -> PageSnapshot:
        return self._ensure().click(selector)

    def type_text(self, selector: str, text: str, *, submit: bool = False) -> PageSnapshot:
        return self._ensure().type_text(selector, text, submit=submit)

    def close(self) -> None:
        if self._inner is not None:
            self._inner.close()
            self._inner = None

    def health(self) -> tuple[bool, str]:
        if not self.enabled:
            return False, "disabled"
        try:
            import playwright  # noqa: F401
        except ImportError:
            return False, "playwright not installed (uv sync --extra browser && playwright install chromium)"
        return True, f"playwright ready (headless={self.headless}, starts on first use)"
