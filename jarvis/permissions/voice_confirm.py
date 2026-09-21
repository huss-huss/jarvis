"""Natural-language yes/no confirmation (text or voice)."""

from __future__ import annotations

import re
from collections.abc import Callable

from jarvis.audio.base import TTSProvider

YES_WORDS = {
    "yes",
    "yeah",
    "yep",
    "yup",
    "sure",
    "ok",
    "okay",
    "confirm",
    "confirmed",
    "affirmative",
    "do it",
    "go ahead",
    "please do",
    "i'm sure",
    "im sure",
    "absolutely",
}
NO_WORDS = {
    "no",
    "nope",
    "nah",
    "cancel",
    "stop",
    "don't",
    "do not",
    "dont",
    "never",
    "negative",
    "abort",
}


def is_affirmative(text: str) -> bool | None:
    """
    Return True/False if clearly yes/no, or None if unclear.
    """
    cleaned = re.sub(r"[^a-zA-Z\s']", " ", (text or "").lower())
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return None

    # Exact short answers
    if cleaned in {"y", "yes", "yeah", "yep", "yup", "sure", "ok", "okay"}:
        return True
    if cleaned in {"n", "no", "nope", "nah", "cancel", "stop"}:
        return False

    has_yes = any(w in cleaned for w in YES_WORDS)
    has_no = any(
        w in cleaned
        for w in NO_WORDS
        # avoid matching "not sure" as yes via "sure" alone when "not" present
    )
    if "not sure" in cleaned or "don't know" in cleaned:
        return None
    if has_no and not has_yes:
        return False
    if has_yes and not has_no:
        return True
    if has_yes and has_no:
        # "yes cancel" → prefer no
        return False
    return None


def humanize_danger_prompt(tool_name: str, summary: str) -> str:
    """Spoken question for dangerous actions."""
    friendly = {
        "delete_file": "delete that file",
        "run_command": "run that command",
    }.get(tool_name, f"run {tool_name.replace('_', ' ')}")
    return (
        f"This is a dangerous action. I am about to {friendly}. "
        f"Details: {summary}. Are you sure? Please say yes or no."
    )


def make_voice_confirm(
    tts: TTSProvider,
    listen: Callable[[], str],
    *,
    max_attempts: int = 2,
) -> Callable[[str], bool]:
    """
    Build a confirm callback that speaks the question and listens for yes/no.
    `prompt` from PermissionManager may be terminal-style; we speak a clearer version when possible.
    """

    def confirm(prompt: str) -> bool:
        # Prefer a natural spoken line; fall back to the given prompt cleaned up.
        spoken = prompt
        if "DANGEROUS" in prompt or "dangerous" in prompt.lower():
            spoken = (
                prompt.replace("DANGEROUS action requested:", "This is dangerous.")
                .replace("`", "")
                .replace("[y/N]", "")
                .replace("Confirm?", "Are you sure?")
                .strip()
            )
            if "say yes or no" not in spoken.lower():
                spoken = spoken.rstrip(".?") + ". Please say yes or no."
        elif "[y/N]" in prompt:
            spoken = prompt.replace("[y/N]", "").replace("`", "") + " Please say yes or no."

        print(f"Jarvis: {spoken}")
        tts.speak(spoken)

        for attempt in range(max_attempts):
            print("Listening for yes / no…")
            try:
                answer = (listen() or "").strip()
            except Exception:  # noqa: BLE001
                answer = ""
            if answer:
                print(f"You: {answer}")
            else:
                print("You: (no speech)")

            decision = is_affirmative(answer)
            if decision is True:
                tts.speak("Okay.")
                return True
            if decision is False:
                tts.speak("Okay, cancelled.")
                return False

            retry = "I didn't catch that. Please say yes or no."
            print(f"Jarvis: {retry}")
            if attempt + 1 < max_attempts:
                tts.speak(retry)

        tts.speak("Cancelled.")
        return False

    return confirm
