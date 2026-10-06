"""Private verification origins: canonical resolution, no fallback.

RED contract for ORIG-001 (R1-R3): the CLI and MCP must resolve both
operational origins from one private dotenv file outside the checkout,
without compiled fallbacks, process overrides, interpolation, network
probes or value leaks in diagnostics.
"""

from __future__ import annotations

import os
import socket
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from automation.verification import origins

DEV_SYN = "https://portal-dev.verification.invalid"
PROD_SYN = "https://portal-prod.verification.invalid"


def _write_profile(path: Path, lines: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(lines, encoding="utf-8")
    return path


def _valid_profile(path: Path, *, dev: str = DEV_SYN, prod: str = PROD_SYN) -> Path:
    return _write_profile(
        path,
        f"SIRHOSP_VERIFY_DEV_ORIGIN={dev}\nSIRHOSP_VERIFY_PROD_ORIGIN={prod}\n",
    )


def test_r1_resolves_both_origins_from_one_private_file(tmp_path):
    profile = _valid_profile(tmp_path / "verification.env")
    resolved = origins.resolve_origins(profile)
    assert resolved.dev == DEV_SYN
    assert resolved.prod == PROD_SYN
    assert origins.resolve_dev_origin(profile) == DEV_SYN


def test_r1_canonical_path_lives_outside_the_checkout():
    assert origins.canonical_profile_path() == (
        Path.home() / ".config" / "sirhosp" / "verification.env"
    )


def test_r1_default_path_follows_home_without_explicit_argument(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    profile = tmp_path / ".config" / "sirhosp" / "verification.env"
    _valid_profile(profile)
    assert origins.resolve_dev_origin() == DEV_SYN


def test_r1_missing_file_is_blocked_without_creating_it(tmp_path):
    profile = tmp_path / "absent" / "verification.env"
    with pytest.raises(origins.OriginConfigError):
        origins.resolve_origins(profile)
    assert not profile.exists()
    assert not profile.parent.exists()


def test_r1_missing_key_is_blocked(tmp_path):
    profile = _write_profile(
        tmp_path / "verification.env", f"SIRHOSP_VERIFY_DEV_ORIGIN={DEV_SYN}\n"
    )
    with pytest.raises(origins.OriginConfigError) as excinfo:
        origins.resolve_origins(profile)
    assert "SIRHOSP_VERIFY_PROD_ORIGIN" in str(excinfo.value)


def test_r1_empty_value_is_blocked(tmp_path):
    profile = _write_profile(
        tmp_path / "verification.env",
        f"SIRHOSP_VERIFY_DEV_ORIGIN=\nSIRHOSP_VERIFY_PROD_ORIGIN={PROD_SYN}\n",
    )
    with pytest.raises(origins.OriginConfigError) as excinfo:
        origins.resolve_origins(profile)
    assert "SIRHOSP_VERIFY_DEV_ORIGIN" in str(excinfo.value)


@pytest.mark.parametrize(
    "bad",
    [
        "http://portal-dev.verification.invalid/",
        "https://user:secret-pw@portal-dev.verification.invalid/",
        "https://portal-dev.verification.invalid/?next=/painel/",
        "https://portal-dev.verification.invalid/#top",
        "https://portal-dev.verification.invalid/app/login/",
        "portal-dev.verification.invalid",
        "https:///painel/",
        "https://portal-dev.verification.invalid:99999/",
        "not a url",
    ],
)
def test_r2_unsafe_values_are_blocked(tmp_path, bad):
    profile = _write_profile(
        tmp_path / "verification.env",
        f"SIRHOSP_VERIFY_DEV_ORIGIN={bad}\nSIRHOSP_VERIFY_PROD_ORIGIN={PROD_SYN}\n",
    )
    with pytest.raises(origins.OriginConfigError) as excinfo:
        origins.resolve_origins(profile)
    assert "SIRHOSP_VERIFY_DEV_ORIGIN" in str(excinfo.value)


@pytest.mark.parametrize(
    "raw,canonical",
    [
        ("https://portal-dev.verification.invalid/", "https://portal-dev.verification.invalid"),
        ("https://portal-dev.verification.invalid:443/", "https://portal-dev.verification.invalid"),
        (
            "HTTPS://PORTAL-DEV.VERIFICATION.INVALID/",
            "https://portal-dev.verification.invalid",
        ),
        ("https://portal-dev.verification.invalid:8443/", "https://portal-dev.verification.invalid:8443"),
    ],
)
def test_r3_representation_is_canonicalized(tmp_path, raw, canonical):
    profile = _valid_profile(tmp_path / "verification.env", dev=raw)
    assert origins.resolve_origins(profile).dev == canonical


@pytest.mark.parametrize(
    "dev,prod",
    [
        (DEV_SYN, DEV_SYN),
        ("https://portal-dev.verification.invalid/", "https://portal-dev.verification.invalid"),
        ("HTTPS://PORTAL-DEV.VERIFICATION.INVALID", "https://portal-dev.verification.invalid/"),
        ("https://portal-dev.verification.invalid:443", "https://portal-dev.verification.invalid"),
    ],
)
def test_r3_dev_matching_prod_is_blocked(tmp_path, dev, prod):
    profile = _valid_profile(tmp_path / "verification.env", dev=dev, prod=prod)
    with pytest.raises(origins.OriginConfigError) as excinfo:
        origins.resolve_origins(profile)
    assert "production" in str(excinfo.value).lower()


def test_r1_process_variable_never_overrides_the_file(tmp_path, monkeypatch):
    profile = _valid_profile(tmp_path / "verification.env")
    monkeypatch.setenv("SIRHOSP_VERIFY_DEV_ORIGIN", "https://override.invalid/")
    monkeypatch.setenv("SIRHOSP_VERIFY_PROD_ORIGIN", "https://override.invalid/")
    assert origins.resolve_origins(profile).dev == DEV_SYN


def test_r1_values_are_not_interpolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SIRHOSP_VERIFY_INNER", "portal-dev.verification.invalid")
    profile = _write_profile(
        tmp_path / "verification.env",
        "SIRHOSP_VERIFY_DEV_ORIGIN=https://${SIRHOSP_VERIFY_INNER}/\n"
        f"SIRHOSP_VERIFY_PROD_ORIGIN={PROD_SYN}\n",
    )
    with pytest.raises(origins.OriginConfigError):
        origins.resolve_origins(profile)


def test_r2_diagnostic_never_reproduces_the_invalid_value(tmp_path):
    secret = "s3cret-userinfo-pw"
    profile = _write_profile(
        tmp_path / "verification.env",
        f"SIRHOSP_VERIFY_DEV_ORIGIN=https://user:{secret}@portal-dev.verification.invalid/\n"
        f"SIRHOSP_VERIFY_PROD_ORIGIN={PROD_SYN}\n",
    )
    with pytest.raises(origins.OriginConfigError) as excinfo:
        origins.resolve_origins(profile)
    assert secret not in str(excinfo.value)
    assert "SIRHOSP_VERIFY_DEV_ORIGIN" in str(excinfo.value)


def test_r1_resolution_leaves_the_process_environment_untouched(tmp_path, monkeypatch):
    profile = _valid_profile(tmp_path / "verification.env")
    before = dict(os.environ)
    origins.resolve_origins(profile)
    assert dict(os.environ) == before
    assert "SIRHOSP_VERIFY_DEV_ORIGIN" not in os.environ


def test_r3_resolution_opens_no_socket(tmp_path, monkeypatch):
    profile = _valid_profile(tmp_path / "verification.env")

    def _refused(*args, **kwargs):
        raise AssertionError("origin resolution must not touch the network")

    monkeypatch.setattr(socket, "socket", _refused)
    assert origins.resolve_origins(profile).dev == DEV_SYN


def test_r1_resolved_pair_is_immutable(tmp_path):
    profile = _valid_profile(tmp_path / "verification.env")
    resolved = origins.resolve_origins(profile)
    with pytest.raises(FrozenInstanceError):
        resolved.dev = "https://other.invalid"  # type: ignore[misc]
