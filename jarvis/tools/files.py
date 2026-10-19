"""File tools — list/find/read/write/move/copy/search/delete within workspace roots."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from jarvis.tools.base import PermissionLevel, Tool, ToolResult
from jarvis.tools.paths import PathDenied, format_roots, resolve_in_roots

TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".py",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".csv",
    ".tsv",
    ".ini",
    ".cfg",
    ".html",
    ".htm",
    ".css",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".rs",
    ".go",
    ".java",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".sh",
    ".zsh",
    ".bash",
    ".xml",
    ".log",
    ".env",
    ".gitignore",
    ".dockerignore",
    ".rst",
    ".sql",
}


class _FileToolBase(Tool):
    def __init__(self, roots: list[Path], *, max_read_bytes: int = 200_000) -> None:
        self.roots = roots
        self.max_read_bytes = max_read_bytes

    def _resolve(self, path: str, *, must_exist: bool = False) -> Path:
        return resolve_in_roots(path, self.roots, must_exist=must_exist)


class ListFilesTool(_FileToolBase):
    name = "list_files"
    description = "List files and folders in a directory inside the workspace."
    permission = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Directory path. Use 'Desktop', 'Documents', 'Downloads', "
                    "'~/Desktop', or a path under workspace roots (default '.')."
                ),
            },
            "limit": {"type": "integer", "description": "Max entries (default 100)."},
        },
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        try:
            path = self._resolve(str(kwargs.get("path") or "."), must_exist=True)
        except (PathDenied, FileNotFoundError, OSError) as exc:
            return ToolResult(success=False, output="", error=str(exc))
        if not path.is_dir():
            return ToolResult(success=False, output="", error=f"Not a directory: {path}")
        limit = max(1, min(int(kwargs.get("limit") or 100), 500))
        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return ToolResult(
                success=False,
                output="",
                error=f"Permission denied reading {path} (macOS may block this folder until you allow Terminal/Cursor).",
            )
        lines = []
        for item in entries[:limit]:
            kind = "dir" if item.is_dir() else "file"
            lines.append(f"{kind}\t{item.name}")
        more = f"\n… and {len(entries) - limit} more" if len(entries) > limit else ""
        header = f"{path} ({len(entries)} entries)\n"
        return ToolResult(success=True, output=header + "\n".join(lines) + more)


class FindFileTool(_FileToolBase):
    name = "find_file"
    description = "Find files by name substring under a workspace directory."
    permission = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Substring to match in file names."},
            "path": {"type": "string", "description": "Root to search (default '.')."},
            "limit": {"type": "integer", "description": "Max results (default 30)."},
        },
        "required": ["name"],
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        needle = str(kwargs.get("name") or "").strip().lower()
        if not needle:
            return ToolResult(success=False, output="", error="name is required")
        try:
            root = self._resolve(str(kwargs.get("path") or "."), must_exist=True)
        except (PathDenied, FileNotFoundError, OSError) as exc:
            return ToolResult(success=False, output="", error=str(exc))
        limit = max(1, min(int(kwargs.get("limit") or 30), 200))
        hits: list[str] = []
        for path in root.rglob("*"):
            if path.is_file() and needle in path.name.lower():
                hits.append(str(path))
                if len(hits) >= limit:
                    break
        if not hits:
            return ToolResult(success=True, output=f"No files matching '{needle}' under {root}")
        return ToolResult(success=True, output="Found:\n" + "\n".join(hits))


class ReadFileTool(_FileToolBase):
    name = "read_file"
    description = "Read a text file inside the workspace (size-capped)."
    permission = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to read."},
            "max_bytes": {"type": "integer", "description": "Optional max bytes to read."},
        },
        "required": ["path"],
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        try:
            path = self._resolve(str(kwargs.get("path") or ""), must_exist=True)
        except (PathDenied, FileNotFoundError, OSError) as exc:
            return ToolResult(success=False, output="", error=str(exc))
        if not path.is_file():
            return ToolResult(success=False, output="", error=f"Not a file: {path}")
        max_bytes = int(kwargs.get("max_bytes") or self.max_read_bytes)
        max_bytes = max(1, min(max_bytes, self.max_read_bytes))
        try:
            data = path.read_bytes()[: max_bytes + 1]
        except OSError as exc:
            return ToolResult(success=False, output="", error=str(exc))
        truncated = len(data) > max_bytes
        data = data[:max_bytes]
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
            note = "\n\n[binary/non-utf8 content; replacement chars used]"
        else:
            note = ""
        if truncated:
            note += f"\n\n[truncated to {max_bytes} bytes]"
        return ToolResult(success=True, output=f"{path}\n\n{text}{note}")


class CreateFileTool(_FileToolBase):
    name = "create_file"
    description = "Create or overwrite a text file inside the workspace."
    permission = PermissionLevel.MODIFICATION
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "overwrite": {"type": "boolean", "description": "Overwrite if exists (default false)."},
        },
        "required": ["path", "content"],
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        try:
            path = self._resolve(str(kwargs.get("path") or ""))
        except (PathDenied, OSError) as exc:
            return ToolResult(success=False, output="", error=str(exc))
        content = str(kwargs.get("content") or "")
        overwrite = bool(kwargs.get("overwrite", False))
        if path.exists() and not overwrite:
            return ToolResult(
                success=False,
                output="",
                error=f"File exists (set overwrite=true to replace): {path}",
            )
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            return ToolResult(success=False, output="", error=str(exc))
        return ToolResult(success=True, output=f"Wrote {path} ({len(content)} chars)")


class MoveFileTool(_FileToolBase):
    name = "move_file"
    description = "Move/rename a file or folder inside the workspace."
    permission = PermissionLevel.MODIFICATION
    parameters = {
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "destination": {"type": "string"},
        },
        "required": ["source", "destination"],
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        try:
            src = self._resolve(str(kwargs.get("source") or ""), must_exist=True)
            dest = self._resolve(str(kwargs.get("destination") or ""))
        except (PathDenied, FileNotFoundError, OSError) as exc:
            return ToolResult(success=False, output="", error=str(exc))
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
        except OSError as exc:
            return ToolResult(success=False, output="", error=str(exc))
        return ToolResult(success=True, output=f"Moved {src} → {dest}")


class CopyFileTool(_FileToolBase):
    name = "copy_file"
    description = "Copy a file or folder inside the workspace."
    permission = PermissionLevel.MODIFICATION
    parameters = {
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "destination": {"type": "string"},
        },
        "required": ["source", "destination"],
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        try:
            src = self._resolve(str(kwargs.get("source") or ""), must_exist=True)
            dest = self._resolve(str(kwargs.get("destination") or ""))
        except (PathDenied, FileNotFoundError, OSError) as exc:
            return ToolResult(success=False, output="", error=str(exc))
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dest)
        except OSError as exc:
            return ToolResult(success=False, output="", error=str(exc))
        return ToolResult(success=True, output=f"Copied {src} → {dest}")


class SearchFilesTool(_FileToolBase):
    name = "search_files"
    description = "Search file contents for a text query under a workspace directory."
    permission = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "path": {"type": "string", "description": "Directory to search (default '.')."},
            "limit": {"type": "integer", "description": "Max matches (default 20)."},
        },
        "required": ["query"],
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        query = str(kwargs.get("query") or "")
        if not query:
            return ToolResult(success=False, output="", error="query is required")
        try:
            root = self._resolve(str(kwargs.get("path") or "."), must_exist=True)
        except (PathDenied, FileNotFoundError, OSError) as exc:
            return ToolResult(success=False, output="", error=str(exc))
        limit = max(1, min(int(kwargs.get("limit") or 20), 100))
        matches: list[str] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in TEXT_SUFFIXES and path.suffix != "":
                continue
            if path.stat().st_size > self.max_read_bytes:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if query in text:
                # first matching line
                line_no = 1
                for line in text.splitlines():
                    if query in line:
                        matches.append(f"{path}:{line_no}: {line.strip()[:200]}")
                        break
                    line_no += 1
                if len(matches) >= limit:
                    break
        if not matches:
            return ToolResult(success=True, output=f"No matches for {query!r} under {root}")
        return ToolResult(success=True, output="Matches:\n" + "\n".join(matches))


class SummarizeFileTool(_FileToolBase):
    name = "summarize_file"
    description = (
        "Load a text file (truncated) so you can summarize it for the user. "
        "Returns file contents with a size cap — you write the summary."
    )
    permission = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
        },
        "required": ["path"],
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        reader = ReadFileTool(self.roots, max_read_bytes=min(self.max_read_bytes, 80_000))
        result = reader.execute(path=str(kwargs.get("path") or ""))
        if not result.success:
            return result
        return ToolResult(
            success=True,
            output=(
                "File loaded for summarization. Read the content below and give the user "
                "a concise summary.\n\n" + result.output
            ),
        )


class DeleteFileTool(_FileToolBase):
    name = "delete_file"
    description = "Delete a file or empty directory inside the workspace. Always requires confirmation."
    permission = PermissionLevel.DANGEROUS
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
        },
        "required": ["path"],
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        try:
            path = self._resolve(str(kwargs.get("path") or ""), must_exist=True)
        except (PathDenied, FileNotFoundError, OSError) as exc:
            return ToolResult(success=False, output="", error=str(exc))
        try:
            if path.is_dir():
                path.rmdir()  # empty dirs only — safer than rmtree by default
            else:
                path.unlink()
        except OSError as exc:
            return ToolResult(success=False, output="", error=str(exc))
        return ToolResult(success=True, output=f"Deleted {path}")


def build_file_tools(roots: list[Path], *, max_read_bytes: int = 200_000) -> list[Tool]:
    kwargs = {"roots": roots, "max_read_bytes": max_read_bytes}
    return [
        ListFilesTool(**kwargs),
        FindFileTool(**kwargs),
        ReadFileTool(**kwargs),
        CreateFileTool(**kwargs),
        MoveFileTool(**kwargs),
        CopyFileTool(**kwargs),
        SearchFilesTool(**kwargs),
        SummarizeFileTool(**kwargs),
        DeleteFileTool(**kwargs),
    ]


def describe_workspace(roots: list[Path]) -> str:
    return f"Workspace roots: {format_roots(roots)}"
