"""System tool unit tests."""

from jarvis.tools.system import GetCurrentTimeTool, OpenApplicationTool


def test_get_current_time():
    result = GetCurrentTimeTool().execute()
    assert result.success is True
    assert "It is" in result.output
    assert "iso" in result.data


def test_open_application_requires_name():
    result = OpenApplicationTool().execute()
    assert result.success is False


def test_close_application_requires_name():
    from jarvis.tools.system import CloseApplicationTool

    result = CloseApplicationTool().execute()
    assert result.success is False


def test_close_accepts_name_alias():
    from jarvis.tools.system import extract_app_name

    assert extract_app_name({"name": "Telegram"}) == "Telegram"
    assert extract_app_name({"application_name": "Safari"}) == "Safari"


def test_resolve_app_aliases():
    from jarvis.tools.system import resolve_app_name

    assert resolve_app_name("chrome") == "Google Chrome"
    assert resolve_app_name("telegram") == "Telegram"
    assert resolve_app_name("Cursor") == "Cursor"
