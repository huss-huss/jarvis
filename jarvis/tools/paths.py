"""Safe path resolution — block traversal outside allowed roots."""

from __future__ import annotations

from pathlib import Path

class PathDenied(ValueError):
    """Raised when a path escapes allowed workspace roots."""


# Typos / nicknames → canonical root folder name
_NAME_ALIASES: dict[str, str] = {
    "desktip": "desktop",
    "desktob": "desktop",
    "my desktop": "desktop",
    "docs": "documents",
    "my documents": "documents",
    "download": "downloads",
    "my downloads": "downloads",
}

# Spoken paths that expand under $HOME (used only if that path is an allowed root)
_HOME_ALIASES: dict[str, str] = {
    "desktop": "~/Desktop",
    "documents": "~/Documents",
    "downloads": "~/Downloads",
    "work": "~/Desktop/Work",
}


def expand_root(raw: str, *, project_root: Path) -> Path:
    text = raw.strip()
    if text in {".", "./"}:
        return project_root.resolve()
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


def resolve_in_roots(
    user_path: str,
    roots: list[Path],
    *,
    must_exist: bool = False,
) -> Path:
    """
    Resolve user_path under one of the allowed roots.
    Absolute paths are allowed only if they stay inside a root.
    Relative paths are tried against each root in order.
    """
    if not roots:
        raise PathDenied("No workspace roots configured")

    raw = (user_path or "").strip() or "."
    key = raw.lower()

    # 1) Match a configured root by folder name ("Desktop", "desktip", …)
    want_name = _NAME_ALIASES.get(key, key)
    for root in roots:
        if want_name == root.name.lower() or key == root.name.lower():
            if must_exist and not root.exists():
                raise FileNotFoundError(f"Path not found: {root}")
            return root.resolve(strict=False)

    # 2) Friendly home aliases → only if that path sits in a root
    alias = _HOME_ALIASES.get(key) or _HOME_ALIASES.get(want_name)
    if alias:
        aliased = Path(alias).expanduser().resolve(strict=False)
        for root in roots:
            root_res = root.resolve(strict=False)
            if aliased == root_res or _is_under(aliased, root):
                if must_exist and not aliased.exists():
                    raise FileNotFoundError(f"Path not found: {aliased}")
                return aliased

    candidate = Path(raw).expanduser()

    resolved: Path | None = None
    if candidate.is_absolute() or str(raw).startswith("~"):
        resolved = candidate.expanduser().resolve(strict=False)
    else:
        # Prefer matching an existing path under any root (not only project root).
        for root in roots:
            trial = (root / candidate).resolve(strict=False)
            if _is_under(trial, root) and trial.exists():
                resolved = trial
                break
        if resolved is None:
            for root in roots:
                trial = (root / candidate).resolve(strict=False)
                if _is_under(trial, root):
                    resolved = trial
                    break
        if resolved is None:
            resolved = (roots[0] / candidate).resolve(strict=False)

    if not any(
        resolved == root.resolve(strict=False) or _is_under(resolved, root) for root in roots
    ):
        raise PathDenied(
            f"Path escapes workspace roots: {user_path}. "
            f"Allowed: {format_roots(roots)}"
        )

    if must_exist and not resolved.exists():
        raise FileNotFoundError(f"Path not found: {resolved}")

    return resolved


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def format_roots(roots: list[Path]) -> str:
    return ", ".join(str(r) for r in roots)
