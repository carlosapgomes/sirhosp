"""Observability contract for the adaptive census orchestrator command.

rc.24: the orchestrator container must emit the module's INFO logs
(`Cycle blocked`, `System eligible`, `Quiet-window D-1 recovery ...`) to
stdout. The command configures root logging at INFO via
``logging.basicConfig`` on every invocation, in every mode, because the
production container runs plain ``manage.py`` with no Django LOGGING
setting — without this call the orchestrator is silent at INFO level and
the nightly quiet-window D-1 gate of the runbook cannot be observed.
"""

from __future__ import annotations

import logging
from unittest import mock

import pytest
from django.core.management import call_command

MODULE = "apps.census.management.commands.run_adaptive_census_cycles"


@pytest.mark.django_db
def test_command_configures_info_logging_on_every_mode() -> None:
    """Every invocation of the orchestrator command configures INFO logs."""
    with mock.patch(f"{MODULE}.logging.basicConfig") as basic_config:
        call_command("run_adaptive_census_cycles", "--dry-run")

    basic_config.assert_called_once_with(level=logging.INFO)
