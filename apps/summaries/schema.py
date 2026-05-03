"""LLM output schema validation (APS-S3).

Provides validate_summary_output() which checks that a JSON dict returned
by the LLM satisfies the mandatory contract:

Required top-level keys:
  - estado_estruturado      (dict)
  - resumo_markdown         (str)
  - mudancas_da_rodada      (list)
  - incertezas              (list)
  - evidencias              (list of {event_id, happened_at, author_name,
                             snippet})
  - alertas_consistencia    (list of {tipo, descricao, evidencias[]})
"""

from __future__ import annotations

from typing import Any

_REQUIRED_KEYS = [
    "estado_estruturado",
    "resumo_markdown",
    "mudancas_da_rodada",
    "incertezas",
    "evidencias",
    "alertas_consistencia",
]

_TYPE_CHECKS = {
    "estado_estruturado": dict,
    "resumo_markdown": str,
    "mudancas_da_rodada": list,
    "incertezas": list,
    "evidencias": list,
    "alertas_consistencia": list,
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

    def _validate_evidence_item(item: Any, *, path: str) -> None:
        if not isinstance(item, dict):
            errors.append(
                f"{path} must be a dict, got {type(item).__name__}."
            )
            return

        # event_id: required, non-empty string
        event_id = item.get("event_id")
        if not event_id or not isinstance(event_id, str):
            errors.append(
                f"{path} is missing a non-empty 'event_id'."
            )

        # happened_at: required, non-empty string
        happened_at = item.get("happened_at")
        if not happened_at or not isinstance(happened_at, str):
            errors.append(
                f"{path} is missing a non-empty 'happened_at'."
            )

        # author_name: required, non-empty string
        author_name = item.get("author_name")
        if not author_name or not isinstance(author_name, str):
            errors.append(
                f"{path} is missing a non-empty 'author_name'."
            )

        # snippet: required, non-empty string
        snippet = item.get("snippet")
        if not snippet or not isinstance(snippet, str):
            errors.append(
                f"{path} is missing a non-empty 'snippet'."
            )

    # ---- Evidence validation ----
    evidencias = data.get("evidencias")
    if isinstance(evidencias, list):
        for idx, item in enumerate(evidencias):
            _validate_evidence_item(item, path=f"evidencias[{idx}]")

    # ---- Consistency alerts validation ----
    alertas = data.get("alertas_consistencia")
    if isinstance(alertas, list):
        for idx, alerta in enumerate(alertas):
            path = f"alertas_consistencia[{idx}]"
            if not isinstance(alerta, dict):
                errors.append(
                    f"{path} must be a dict, got {type(alerta).__name__}."
                )
                continue

            tipo = alerta.get("tipo")
            if not tipo or not isinstance(tipo, str):
                errors.append(f"{path} is missing a non-empty 'tipo'.")

            descricao = alerta.get("descricao")
            if not descricao or not isinstance(descricao, str):
                errors.append(f"{path} is missing a non-empty 'descricao'.")

            alerta_evidencias = alerta.get("evidencias")
            if not isinstance(alerta_evidencias, list):
                errors.append(f"{path}.evidencias must be a list.")
                continue

            for ev_idx, item in enumerate(alerta_evidencias):
                _validate_evidence_item(
                    item,
                    path=f"{path}.evidencias[{ev_idx}]",
                )

    return errors
