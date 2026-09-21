"""Voice / text confirmation parsing tests."""

from jarvis.permissions.voice_confirm import is_affirmative, make_voice_confirm


def test_is_affirmative_yes():
    assert is_affirmative("yes") is True
    assert is_affirmative("Yeah, do it") is True
    assert is_affirmative("I'm sure") is True


def test_is_affirmative_no():
    assert is_affirmative("no") is False
    assert is_affirmative("nope cancel") is False
    assert is_affirmative("don't") is False


def test_is_affirmative_unclear():
    assert is_affirmative("") is None
    assert is_affirmative("maybe later") is None


def test_voice_confirm_yes():
    spoken: list[str] = []

    class _TTS:
        def speak(self, text: str) -> None:
            spoken.append(text)

        def stop(self) -> None:
            return None

    answers = iter(["yes"])
    confirm = make_voice_confirm(_TTS(), lambda: next(answers))
    assert confirm("DANGEROUS action requested: `delete_file`. Confirm? [y/N] ") is True
    assert spoken  # asked aloud


def test_voice_confirm_no():
    class _TTS:
        def speak(self, text: str) -> None:
            return None

        def stop(self) -> None:
            return None

    confirm = make_voice_confirm(_TTS(), lambda: "no")
    assert confirm("Are you sure? Please say yes or no.") is False
