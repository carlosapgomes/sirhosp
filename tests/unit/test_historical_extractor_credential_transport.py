"""Credential-safe subprocess transport for historical extractors (RPSA-S7A).

Covers the spec requirement "Historical extractor subprocess credentials are
not argv values" and its three scenarios:

- starts automation: the four historical services (admissions, discharges,
  deaths, official census) build subprocess commands WITHOUT
  ``--username``/``--password`` values and pass credentials only through a
  scoped child environment using exactly the keys
  ``SOURCE_SYSTEM_USERNAME``/``SOURCE_SYSTEM_PASSWORD``;
- credential is missing: each automation entry point resolves credentials
  env-first, keeps ``--username``/``--password`` as a manual CLI fallback
  only when the environment value is absent, and exits non-zero with one
  fixed message that names neither the missing field nor any credential
  value;
- process inspection occurs: credential values never appear in argv, and
  the parent environment is never mutated (``os.environ`` intact after
  service calls).

Non-credential argv (source URL, dates, headless, output dir, reference
date) stays unchanged. The subprocess layer is mocked; only synthetic
sentinel credentials are used and the real source system is never
contacted.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from apps.ingestion.extractors.subprocess_utils import SubprocessTimeoutError
from apps.ingestion.models import IngestionRun

SENTINEL_USERNAME = "user-sentinel"
SENTINEL_PASSWORD = "pass-sentinel"
SENTINEL_URL = "https://extractor.example.com"

# Keys that must never appear in the fixed missing-credential message.
_FORBIDDEN_IN_MESSAGE = (
    "username",
    "password",
    "usuário",
    "senha",
    "SOURCE_SYSTEM_",
    SENTINEL_USERNAME,
    SENTINEL_PASSWORD,
)


def _make_capturing_run_subprocess(outputs: list):
    """Build a ``run_subprocess`` fake that records cmd and kwargs per call.

    Each element of *outputs* describes one invocation:

    - ``None``: subprocess succeeds and writes no output file;
    - ``{"timeout": True}``: raises ``SubprocessTimeoutError``.

    The fake records ``(cmd, kwargs)`` tuples in ``calls``.
    """
    calls: list[tuple[list[str], dict]] = []

    def _side_effect(cmd, timeout=None, check=False, env=None, **kwargs):
        calls.append((list(cmd), {"env": env, **kwargs}))
        spec = outputs[len(calls) - 1] if len(calls) <= len(outputs) else None
        if isinstance(spec, dict) and spec.get("timeout"):
            raise SubprocessTimeoutError(
                cmd=list(cmd),
                timeout=timeout if timeout is not None else 600,
                output="",
                stderr=f"login failed for {SENTINEL_USERNAME}",
            )
        proc = MagicMock()
        proc.stdout = ""
        proc.stderr = ""
        proc.returncode = 0
        return proc

    _side_effect.calls = calls  # type: ignore[attr-defined]
    return _side_effect


def _assert_scoped_env(call_kwargs: dict) -> dict:
    """Assert the captured call passed the scoped child environment.

    Returns the captured ``env`` for further assertions.
    """
    assert "env" in call_kwargs, "run_subprocess must receive env= explicitly"
    child_env = call_kwargs["env"]
    # Built from os.environ.copy() with ONLY the two credential overrides.
    expected = dict(os.environ)
    expected["SOURCE_SYSTEM_USERNAME"] = SENTINEL_USERNAME
    expected["SOURCE_SYSTEM_PASSWORD"] = SENTINEL_PASSWORD
    assert child_env == expected
    # A copy, never the parent mapping itself.
    assert child_env is not os.environ
    return child_env


def _assert_parent_env_not_mutated() -> None:
    """The parent environment must stay intact after the service call."""
    assert os.environ.get("SOURCE_SYSTEM_USERNAME") != SENTINEL_USERNAME
    assert os.environ.get("SOURCE_SYSTEM_PASSWORD") != SENTINEL_PASSWORD
    assert os.environ.get("S7A_PARENT_PROBE") == "probe-value"


# =========================================================================
# Services: credentials leave argv and travel only in the scoped child env
# =========================================================================


@pytest.mark.django_db
class TestAdmissionsCredentialTransport:
    """admissions: argv clean, scoped env only."""

    SERVICE_PATH = "apps.admissions.services"

    def test_credentials_absent_from_argv_present_only_in_child_env(
        self, monkeypatch,
    ):
        from apps.admissions.services import run_admission_extraction

        monkeypatch.setenv("S7A_PARENT_PROBE", "probe-value")
        fake = _make_capturing_run_subprocess([None])
        with patch(
            f"{self.SERVICE_PATH}.resolve_source_credentials"
        ) as mock_creds, patch(
            f"{self.SERVICE_PATH}.run_subprocess", side_effect=fake,
        ):
            mock_creds.return_value.url = SENTINEL_URL
            mock_creds.return_value.username = SENTINEL_USERNAME
            mock_creds.return_value.password = SENTINEL_PASSWORD
            result = run_admission_extraction(
                start_date="01/06/2026", end_date="02/06/2026",
                headless=True,
            )

        assert result.success is True
        assert len(fake.calls) == 1
        cmd, call_kwargs = fake.calls[0]

        # Credentials are absent from argv (no flags, no values).
        assert "--username" not in cmd
        assert "--password" not in cmd
        assert SENTINEL_USERNAME not in cmd
        assert SENTINEL_PASSWORD not in cmd

        # Scoped child env carries exactly the two overrides.
        _assert_scoped_env(call_kwargs)
        _assert_parent_env_not_mutated()

        # Compatibility: non-credential argv unchanged.
        assert str(cmd[cmd.index("--source-url") + 1]) == SENTINEL_URL
        assert cmd[cmd.index("--start-date") + 1] == "01/06/2026"
        assert cmd[cmd.index("--end-date") + 1] == "02/06/2026"
        assert "--headless" in cmd
        assert "--output-dir" in cmd

    def test_timeout_error_paths_never_echo_credentials(self, monkeypatch):
        from apps.admissions.services import run_admission_extraction

        fake = _make_capturing_run_subprocess([{"timeout": True}])
        with patch(
            f"{self.SERVICE_PATH}.resolve_source_credentials"
        ) as mock_creds, patch(
            f"{self.SERVICE_PATH}.run_subprocess", side_effect=fake,
        ):
            mock_creds.return_value.url = SENTINEL_URL
            mock_creds.return_value.username = SENTINEL_USERNAME
            mock_creds.return_value.password = SENTINEL_PASSWORD
            result = run_admission_extraction(
                start_date="01/06/2026", end_date="02/06/2026",
                headless=True,
            )

        assert result.success is False
        cmd, _ = fake.calls[0]
        assert SENTINEL_PASSWORD not in cmd
        dumped = (
            result.error_message
            + (IngestionRun.objects.get(
                pk=result.ingestion_run_id
            ).error_message or "")
        )
        for stage in IngestionRun.objects.get(
            pk=result.ingestion_run_id
        ).stage_metrics.all():
            dumped += str(stage.details_json)
        assert SENTINEL_USERNAME not in dumped
        assert SENTINEL_PASSWORD not in dumped


@pytest.mark.django_db
class TestDischargesCredentialTransport:
    """discharges: argv clean, scoped env only (both S7 attempts)."""

    SERVICE_PATH = "apps.discharges.extraction_service"

    def test_credentials_absent_from_argv_present_only_in_child_env(
        self, monkeypatch,
    ):
        from apps.discharges.extraction_service import run_discharge_extraction

        monkeypatch.setenv("S7A_PARENT_PROBE", "probe-value")
        # Empty first attempt + empty confirmation => confirmed zero,
        # proving BOTH invocations transport credentials via env only.
        fake = _make_capturing_run_subprocess([None, None])
        with patch(
            f"{self.SERVICE_PATH}.resolve_source_credentials"
        ) as mock_creds, patch(
            f"{self.SERVICE_PATH}.run_subprocess", side_effect=fake,
        ), patch(f"{self.SERVICE_PATH}.call_command"):
            mock_creds.return_value.url = SENTINEL_URL
            mock_creds.return_value.username = SENTINEL_USERNAME
            mock_creds.return_value.password = SENTINEL_PASSWORD
            result = run_discharge_extraction(date="01/06/2026", headless=True)

        assert result.success is True
        assert result.zero_confirmed is True
        assert len(fake.calls) == 2
        for cmd, call_kwargs in fake.calls:
            assert "--username" not in cmd
            assert "--password" not in cmd
            assert SENTINEL_USERNAME not in cmd
            assert SENTINEL_PASSWORD not in cmd
            _assert_scoped_env(call_kwargs)
            # Compatibility: non-credential argv unchanged.
            assert str(cmd[cmd.index("--source-url") + 1]) == SENTINEL_URL
            assert cmd[cmd.index("--date") + 1] == "01/06/2026"
            assert "--reference-date" in cmd
            assert "--headless" in cmd
            assert "--output-dir" in cmd
        _assert_parent_env_not_mutated()


@pytest.mark.django_db
class TestDeathsCredentialTransport:
    """deaths: argv clean, scoped env only."""

    SERVICE_PATH = "apps.deaths.services"

    def test_credentials_absent_from_argv_present_only_in_child_env(
        self, monkeypatch,
    ):
        from apps.deaths.services import run_death_extraction

        monkeypatch.setenv("S7A_PARENT_PROBE", "probe-value")
        fake = _make_capturing_run_subprocess([None])
        with patch(
            f"{self.SERVICE_PATH}.resolve_source_credentials"
        ) as mock_creds, patch(
            f"{self.SERVICE_PATH}.run_subprocess", side_effect=fake,
        ):
            mock_creds.return_value.url = SENTINEL_URL
            mock_creds.return_value.username = SENTINEL_USERNAME
            mock_creds.return_value.password = SENTINEL_PASSWORD
            result = run_death_extraction(
                start_date="01/06/2026", end_date="02/06/2026",
                headless=True,
            )

        assert result.success is True
        assert len(fake.calls) == 1
        cmd, call_kwargs = fake.calls[0]
        assert "--username" not in cmd
        assert "--password" not in cmd
        assert SENTINEL_USERNAME not in cmd
        assert SENTINEL_PASSWORD not in cmd
        _assert_scoped_env(call_kwargs)
        _assert_parent_env_not_mutated()
        assert str(cmd[cmd.index("--source-url") + 1]) == SENTINEL_URL
        assert cmd[cmd.index("--start-date") + 1] == "01/06/2026"
        assert cmd[cmd.index("--end-date") + 1] == "02/06/2026"
        assert "--headless" in cmd
        assert "--output-dir" in cmd


@pytest.mark.django_db
class TestOfficialCensusCredentialTransport:
    """official census: argv clean, scoped env only."""

    SERVICE_PATH = "apps.census.services"

    def test_credentials_absent_from_argv_present_only_in_child_env(
        self, monkeypatch,
    ):
        from apps.census.services import run_official_census_extraction

        monkeypatch.setenv("S7A_PARENT_PROBE", "probe-value")
        fake = _make_capturing_run_subprocess([None])
        with patch(
            f"{self.SERVICE_PATH}.resolve_source_credentials"
        ) as mock_creds, patch(
            f"{self.SERVICE_PATH}.run_subprocess", side_effect=fake,
        ):
            mock_creds.return_value.url = SENTINEL_URL
            mock_creds.return_value.username = SENTINEL_USERNAME
            mock_creds.return_value.password = SENTINEL_PASSWORD
            result = run_official_census_extraction(
                date="01/06/2026", headless=True,
            )

        assert result.success is True
        assert len(fake.calls) == 1
        cmd, call_kwargs = fake.calls[0]
        assert "--username" not in cmd
        assert "--password" not in cmd
        assert SENTINEL_USERNAME not in cmd
        assert SENTINEL_PASSWORD not in cmd
        _assert_scoped_env(call_kwargs)
        _assert_parent_env_not_mutated()
        assert str(cmd[cmd.index("--source-url") + 1]) == SENTINEL_URL
        assert cmd[cmd.index("--date") + 1] == "01/06/2026"
        assert "--headless" in cmd
        assert "--output-dir" in cmd


# =========================================================================
# Automation entry points: env-first, CLI fallback, fixed non-echo failure
# =========================================================================


class _EntryPointContract:
    """Shared contract pinned for every automation entry point."""

    MODULE: ModuleType  # bound by each subclass below
    SCRIPT_FLAG = "--source-url"

    def _parse(self, extra: list[str], monkeypatch):
        script = Path(str(self.MODULE.__file__)).name
        monkeypatch.setattr(
            sys,
            "argv",
            [script, self.SCRIPT_FLAG, SENTINEL_URL, *extra],
        )
        return self.MODULE.parse_args()

    def test_env_values_win_over_cli_flags(self, monkeypatch):
        monkeypatch.setenv("SOURCE_SYSTEM_USERNAME", SENTINEL_USERNAME)
        monkeypatch.setenv("SOURCE_SYSTEM_PASSWORD", SENTINEL_PASSWORD)
        args = self._parse(
            ["--username", "cli-user", "--password", "cli-pass"],
            monkeypatch,
        )
        assert self.MODULE.resolve_credentials(args) == (
            SENTINEL_USERNAME,
            SENTINEL_PASSWORD,
        )

    def test_cli_flags_are_fallback_when_env_absent(self, monkeypatch):
        monkeypatch.delenv("SOURCE_SYSTEM_USERNAME", raising=False)
        monkeypatch.delenv("SOURCE_SYSTEM_PASSWORD", raising=False)
        args = self._parse(
            ["--username", "cli-user", "--password", "cli-pass"],
            monkeypatch,
        )
        assert self.MODULE.resolve_credentials(args) == (
            "cli-user",
            "cli-pass",
        )

    def test_missing_both_exits_nonzero_with_fixed_non_echoing_message(
        self, monkeypatch, capsys,
    ):
        monkeypatch.delenv("SOURCE_SYSTEM_USERNAME", raising=False)
        monkeypatch.delenv("SOURCE_SYSTEM_PASSWORD", raising=False)
        script = Path(str(self.MODULE.__file__)).name
        monkeypatch.setattr(
            sys, "argv", [script, self.SCRIPT_FLAG, SENTINEL_URL]
        )
        with pytest.raises(SystemExit) as exc_info:
            self.MODULE.main()

        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        output = captured.out + captured.err
        assert self.MODULE.MISSING_CREDENTIALS_MESSAGE in output
        for forbidden in _FORBIDDEN_IN_MESSAGE:
            assert forbidden not in output

    def test_help_documents_env_first_precedence(self, monkeypatch, capsys):
        monkeypatch.setattr(
            sys,
            "argv",
            [
                Path(str(self.MODULE.__file__)).name,
                self.SCRIPT_FLAG,
                SENTINEL_URL,
                "--help",
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            self.MODULE.parse_args()
        assert exc_info.value.code == 0
        output = capsys.readouterr().out
        assert "SOURCE_SYSTEM_USERNAME" in output
        assert "SOURCE_SYSTEM_PASSWORD" in output


class TestAdmissionsEntryPoint(_EntryPointContract):
    """extract_admissions.py credential resolution contract."""

    from automation.source_system.admissions import (
        extract_admissions as MODULE,
    )


class TestDischargesEntryPoint(_EntryPointContract):
    """extract_discharges.py credential resolution contract."""

    from automation.source_system.discharges import (
        extract_discharges as MODULE,
    )


class TestDeathsEntryPoint(_EntryPointContract):
    """extract_deaths.py credential resolution contract."""

    from automation.source_system.deaths import extract_deaths as MODULE


class TestOfficialCensusEntryPoint(_EntryPointContract):
    """extract_official_census.py credential resolution contract."""

    from automation.source_system.official_census import (
        extract_official_census as MODULE,
    )
