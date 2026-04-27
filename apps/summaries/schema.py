"""LLM output schema validation (APS-S3).

Provides validate_summary_output() which checks that a JSON dict returned
by the LLM satisfies the mandatory contract:

Required top-level keys:
  - estado_estruturado      (dict)
  - resumo_markdown         (str)
  - mudancas_da_rodada      (list)
  - incertezas              (list)
  - evidencias              (list of {event_id (non-empty str), snippet
                             (non-empty str)})
"""

from __future__ import annotations

from typing import Any

_REQUIRED_KEYS = [
    "estado_estruturado",
    "resumo_markdown",
    "mudancas_da_rodada",
    "incertezas",
    "evidencias",
]

_TYPE_CHECKS = {
    "estado_estruturado": dict,
    "resumo_markdown": str,
    "mudancas_da_rodada": list,
    "incertezas": list,
    "evidencias": list,
}


def validate_summary_output(data: dict[str, Any]) -> list[str]:
    """Validate an LLM summary output dict.

    Args:
        data: The parsed JSON response from the LLM.

    Returns:
        List of human-readable error messages.  An empty list means the
        output is valid.
    """
    errors: list[str] = []

    # ---- Required keys ----
    for key in _REQUIRED_KEYS:
        if key not in data:
            errors.append(
                f"Missing required field: '{key}'."
            )

    # ---- Type checks (only for keys that *are* present) ----
    for key, expected_type in _TYPE_CHECKS.items():
        if key not in data:
            continue
        value = data[key]
        if not isinstance(value, expected_type):
            errors.append(
                f"Field '{key}' must be a {expected_type.__name__}, "
                f"got {type(value).__name__}."
            )

    # ---- Evidence validation ----
    evidencias = data.get("evidencias")
    if isinstance(evidencias, list):
        for idx, item in enumerate(evidencias):
            if not isinstance(item, dict):
                errors.append(
                    f"evidencias[{idx}] must be a dict, "
                    f"got {type(item).__name__}."
                )
                continue
            # event_id: required, non-empty string
            event_id = item.get("event_id")
            if not event_id or not isinstance(event_id, str):
                errors.append(
                    f"evidencias[{idx}] is missing a non-empty 'event_id'."
                )
            # snippet: required, non-empty string
            snippet = item.get("snippet")
            if not snippet or not isinstance(snippet, str):
                errors.append(
                    f"evidencias[{idx}] is missing a non-empty 'snippet'."
                )

    return errors
