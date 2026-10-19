"""RAG tools — ingest / search / project context."""

from __future__ import annotations

from typing import Any

from jarvis.rag.extract import ExtractError
from jarvis.rag.service import RagService
from jarvis.tools.base import PermissionLevel, Tool, ToolResult
from jarvis.tools.paths import PathDenied


class IngestDocumentTool(Tool):
    name = "ingest_document"
    description = (
        "Index a single document into local RAG (txt/md/json/csv/pdf/docx). "
        "Path must be under workspace roots."
    )
    permission = PermissionLevel.MODIFICATION
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "project": {
                "type": "string",
                "description": "Optional project name (default: active project).",
            },
        },
        "required": ["path"],
    }

    def __init__(self, rag: RagService) -> None:
        self.rag = rag

    def execute(self, **kwargs: Any) -> ToolResult:
        path = str(kwargs.get("path") or "").strip()
        project = kwargs.get("project")
        if not path:
            return ToolResult(success=False, output="", error="path is required")
        try:
            result = self.rag.ingest_document(
                path, project=str(project) if project else None
            )
        except (ExtractError, PathDenied, FileNotFoundError, OSError) as exc:
            return ToolResult(success=False, output="", error=str(exc))
        return ToolResult(success=True, output=result.message)


class IngestFolderTool(Tool):
    name = "ingest_folder"
    description = "Index supported documents under a folder into local RAG."
    permission = PermissionLevel.MODIFICATION
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "project": {"type": "string"},
            "recursive": {"type": "boolean"},
            "limit": {"type": "integer"},
        },
        "required": ["path"],
    }

    def __init__(self, rag: RagService) -> None:
        self.rag = rag

    def execute(self, **kwargs: Any) -> ToolResult:
        path = str(kwargs.get("path") or "").strip()
        if not path:
            return ToolResult(success=False, output="", error="path is required")
        try:
            results = self.rag.ingest_folder(
                path,
                project=str(kwargs["project"]) if kwargs.get("project") else None,
                recursive=bool(kwargs.get("recursive", True)),
                limit=int(kwargs.get("limit") or 100),
            )
        except (ExtractError, PathDenied, FileNotFoundError, OSError) as exc:
            return ToolResult(success=False, output="", error=str(exc))
        indexed = [r for r in results if not r.skipped]
        skipped = [r for r in results if r.skipped]
        lines = [f"Indexed {len(indexed)} file(s), skipped {len(skipped)}."]
        for r in indexed[:20]:
            lines.append(f"- {r.message}")
        for r in skipped[:10]:
            lines.append(f"- skip: {r.message}")
        return ToolResult(success=True, output="\n".join(lines))


class SearchDocsTool(Tool):
    name = "search_docs"
    description = (
        "Semantic search over ingested documents. Use for questions about requirements, "
        "notes, or project files that were indexed."
    )
    permission = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "project": {"type": "string", "description": "Limit to a project (optional)."},
            "limit": {"type": "integer"},
        },
        "required": ["query"],
    }

    def __init__(self, rag: RagService) -> None:
        self.rag = rag

    def execute(self, **kwargs: Any) -> ToolResult:
        query = str(kwargs.get("query") or "").strip()
        if not query:
            return ToolResult(success=False, output="", error="query is required")
        output = self.rag.format_tool_hits(
            query,
            top_k=int(kwargs.get("limit") or self.rag.top_k),
            project=str(kwargs["project"]) if kwargs.get("project") else None,
        )
        return ToolResult(success=True, output=output)


class ListIngestedTool(Tool):
    name = "list_ingested"
    description = "List documents currently indexed in RAG."
    permission = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "project": {"type": "string"},
            "limit": {"type": "integer"},
        },
    }

    def __init__(self, rag: RagService) -> None:
        self.rag = rag

    def execute(self, **kwargs: Any) -> ToolResult:
        docs = self.rag.list_documents(
            project=str(kwargs["project"]) if kwargs.get("project") else None,
        )
        limit = max(1, min(int(kwargs.get("limit") or 50), 200))
        docs = docs[:limit]
        if not docs:
            return ToolResult(success=True, output="No documents ingested yet.")
        lines = [f"[{d.project}] {d.path} ({d.chunk_count} chunks)" for d in docs]
        return ToolResult(success=True, output="Ingested documents:\n" + "\n".join(lines))


class SwitchProjectTool(Tool):
    name = "switch_project"
    description = "Set the active RAG project context for ingest/search defaults."
    permission = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "project": {"type": "string"},
        },
        "required": ["project"],
    }

    def __init__(self, rag: RagService) -> None:
        self.rag = rag

    def execute(self, **kwargs: Any) -> ToolResult:
        name = str(kwargs.get("project") or "").strip()
        if not name:
            return ToolResult(success=False, output="", error="project is required")
        active = self.rag.switch_project(name)
        return ToolResult(success=True, output=f"Active project is now '{active}'.")


class ListProjectsTool(Tool):
    name = "list_projects"
    description = "List RAG projects and how many documents each has."
    permission = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    def __init__(self, rag: RagService) -> None:
        self.rag = rag

    def execute(self, **kwargs: Any) -> ToolResult:
        active = self.rag.active_project()
        rows = self.rag.list_projects()
        if not rows:
            return ToolResult(
                success=True,
                output=f"No projects yet. Active context: '{active}'. Ingest documents to create one.",
            )
        lines = [f"Active project: {active}"]
        for name, count in rows:
            mark = " *" if name == active else ""
            lines.append(f"- {name}: {count} doc(s){mark}")
        return ToolResult(success=True, output="\n".join(lines))


def build_rag_tools(rag: RagService) -> list[Tool]:
    return [
        IngestDocumentTool(rag),
        IngestFolderTool(rag),
        SearchDocsTool(rag),
        ListIngestedTool(rag),
        SwitchProjectTool(rag),
        ListProjectsTool(rag),
    ]
