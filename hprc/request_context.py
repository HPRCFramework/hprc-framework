"""Request normalization.

HPRC integrates with any web framework but never imports one (FastAPI/Flask/Django).
Instead it normalizes whatever request object the application passes into a plain dict
with a stable shape::

    {
        "query":  {...},   # query-string parameters
        "path":   {...},   # path parameters
        "method": "GET",
    }

Templates then address this via ``request.query.*``, ``request.path.*`` and
``request.method``.
"""

from __future__ import annotations

from typing import Any, Dict


def _to_plain_dict(value: Any) -> Dict[str, Any]:
    """Best-effort conversion of a mapping-like object to a plain dict."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    # Starlette/FastAPI use multidicts that support .items() and have keys.
    if hasattr(value, "items"):
        try:
            return dict(value.items())
        except Exception:  # pragma: no cover - defensive
            pass
    return {}


def normalize_request(request: Any) -> Dict[str, Any]:
    """Normalize an arbitrary request object into HPRC's request namespace.

    Supported inputs:

    * ``None`` -> empty namespace.
    * A plain ``dict`` already shaped as ``{"query": ..., "path": ..., "method": ...}``.
    * A FastAPI/Starlette ``Request`` (uses ``query_params``, ``path_params``,
      ``method``).
    * Any object exposing ``query``/``path``/``method`` or
      ``query_params``/``path_params``/``method`` attributes.
    """
    if request is None:
        return {"query": {}, "path": {}, "method": ""}

    # Already a normalized / simple dict.
    if isinstance(request, dict):
        return {
            "query": _to_plain_dict(request.get("query")),
            "path": _to_plain_dict(request.get("path")),
            "method": request.get("method", "") or "",
        }

    query = getattr(request, "query_params", None)
    if query is None:
        query = getattr(request, "query", None)

    path = getattr(request, "path_params", None)
    if path is None:
        path = getattr(request, "path", None)

    method = getattr(request, "method", "") or ""

    return {
        "query": _to_plain_dict(query),
        "path": _to_plain_dict(path),
        "method": method,
    }


def resolve_path(root: Dict[str, Any], dotted: str) -> Any:
    """Resolve a dotted path like ``customer.profile.name`` against ``root``.

    Supports dict keys, object attributes and integer list indices. Returns an
    empty string when any segment is missing so templates degrade gracefully.
    """
    current: Any = root
    for part in dotted.split("."):
        if current is None:
            return ""
        if isinstance(current, dict):
            if part not in current:
                return ""
            current = current[part]
        elif isinstance(current, (list, tuple)):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return ""
        else:
            if not hasattr(current, part):
                return ""
            current = getattr(current, part)
    return current
