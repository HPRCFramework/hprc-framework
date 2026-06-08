"""Rule evaluation.

Rules keep business logic out of templates. A template only references a rule by
name (``condition="is_premium_customer"``); the actual predicate lives in Python
and is supplied externally via :class:`~hprc.config.HPRCConfig`.

There is intentionally **no expression parsing** in templates — only named rule
lookup.
"""

from __future__ import annotations

from typing import Any, Callable, Dict


class RuleError(Exception):
    """Raised when a template references a rule that was never registered."""


def evaluate_rule(
    name: str,
    rules: Dict[str, Callable[[Dict[str, Any]], bool]],
    context: Dict[str, Any],
) -> bool:
    """Evaluate the named rule against ``context`` and coerce the result to bool.

    Raises :class:`RuleError` if the rule is not registered. A blank/empty name
    is treated as "no condition" and returns ``True``.
    """
    if not name:
        return True
    if name not in rules:
        raise RuleError(
            f"Rule '{name}' is referenced in a template but was not registered."
        )
    return bool(rules[name](context))
