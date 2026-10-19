"""Phase 5 file / path safety tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.tools.files import build_file_tools
from jarvis.tools.paths import PathDenied, resolve_in_roots
from jarvis.tools.registry import ToolRegistry


def test_path_traversal_blocked(tmp_path: Path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "ok.txt").write_text("hi", encoding="utf-8")
    with pytest.raises(PathDenied):
        resolve_in_roots("../ok.txt", [root])
    # Absolute escape
    outside = tmp_path / "secret.txt"
    outside.write_text("nope", encoding="utf-8")
    with pytest.raises(PathDenied):
        resolve_in_roots(str(outside), [root])


def test_file_tools_roundtrip(tmp_path: Path):
    root = tmp_path / "ws"
    root.mkdir()
    registry = ToolRegistry()
    for tool in build_file_tools([root]):
        registry.register(tool)

    created = registry.execute(
        "create_file",
        {"path": "notes/hello.txt", "content": "Atlas project notes", "overwrite": True},
    )
    assert created.success, created.error

    listed = registry.execute("list_files", {"path": "notes"})
    assert listed.success
    assert "hello.txt" in listed.output

    read = registry.execute("read_file", {"path": "notes/hello.txt"})
    assert read.success
    assert "Atlas" in read.output

    found = registry.execute("find_file", {"name": "hello", "path": "."})
    assert found.success
    assert "hello.txt" in found.output

    searched = registry.execute("search_files", {"query": "Atlas", "path": "."})
    assert searched.success
    assert "hello.txt" in searched.output

    copied = registry.execute(
        "copy_file",
        {"source": "notes/hello.txt", "destination": "notes/hello-copy.txt"},
    )
    assert copied.success

    moved = registry.execute(
        "move_file",
        {"source": "notes/hello-copy.txt", "destination": "notes/renamed.txt"},
    )
    assert moved.success

    deleted = registry.execute("delete_file", {"path": "notes/renamed.txt"})
    assert deleted.success
    assert not (root / "notes" / "renamed.txt").exists()


def test_desktop_alias_resolves(tmp_path: Path, monkeypatch):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    (desktop / "note.txt").write_text("hi", encoding="utf-8")
    project = tmp_path / "proj"
    project.mkdir()
    roots = [project, desktop]
    from jarvis.tools.paths import resolve_in_roots

    assert resolve_in_roots("Desktop", roots) == desktop.resolve()
    assert resolve_in_roots("desktip", roots) == desktop.resolve()
    tool = build_file_tools(roots)[0]  # list_files
    result = tool.execute(path="Desktop")
    assert result.success
    assert "note.txt" in result.output
    root = tmp_path / "ws"
    root.mkdir()
    nested = root / "box"
    nested.mkdir()
    (nested / "f.txt").write_text("x", encoding="utf-8")
    registry = ToolRegistry()
    for tool in build_file_tools([root]):
        registry.register(tool)
    result = registry.execute("delete_file", {"path": "box"})
    assert result.success is False
    assert nested.exists()
