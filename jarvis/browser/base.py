"""Browser provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class PageSnapshot:
    url: str
    title: str
    text: str


class BrowserProvider(ABC):
    @abstractmethod
    def open(self, url: str = "about:blank") -> PageSnapshot:
        raise NotImplementedError

    @abstractmethod
    def navigate(self, url: str) -> PageSnapshot:
        raise NotImplementedError

    @abstractmethod
    def get_text(self, *, max_chars: int = 12_000) -> PageSnapshot:
        raise NotImplementedError

    @abstractmethod
    def click(self, selector: str) -> PageSnapshot:
        raise NotImplementedError

    @abstractmethod
    def type_text(self, selector: str, text: str, *, submit: bool = False) -> PageSnapshot:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    def health(self) -> tuple[bool, str]:
        return True, "ok"
