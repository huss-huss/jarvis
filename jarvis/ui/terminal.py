"""Terminal UI helpers."""

from __future__ import annotations


def print_banner(model: str, status: str = "Ready") -> None:
    print()
    print("JARVIS Local Assistant")
    print(f"Model: {model}")
    print(f"Status: {status}")
    print()


def confirm_yes_no(prompt: str) -> bool:
    try:
        answer = input(prompt).strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}
